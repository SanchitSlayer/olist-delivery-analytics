"""Build the late-delivery modelling table from the dbt marts.

Every feature here is known at the moment the order is placed. Nothing from the
review, the carrier hand-off or the actual delivery date is used, so the model
could score an order the second it comes in.
"""

from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "warehouse" / "olist.duckdb"

TARGET = "is_late"

NUMERIC_FEATURES = [
    "promised_days",
    "items_value",
    "freight_value",
    "freight_to_price_ratio",
    "item_count",
    "total_weight_g",
    "total_volume_cm3",
]

CATEGORICAL_FEATURES = [
    "main_category",
    "customer_state",
    "seller_state",
    "is_same_state",
    "purchase_month",
    "purchase_weekday",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

QUERY = """
    select
        order_id,
        purchased_at,
        promised_days,
        cast(items_value as double)                         as items_value,
        cast(freight_value as double)                       as freight_value,
        cast(freight_value as double)
            / nullif(cast(items_value as double), 0)        as freight_to_price_ratio,
        item_count,
        total_weight_g,
        total_volume_cm3,
        main_category,
        customer_state,
        seller_state,
        case when is_same_state then 'yes' else 'no' end    as is_same_state,
        cast(month(purchased_at) as varchar)                as purchase_month,
        dayname(purchased_at)                               as purchase_weekday,
        cast(is_late as integer)                            as is_late
    from marts.fct_orders
    where is_delivered
    order by purchased_at, order_id
"""


def load_model_data(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Return one row per delivered order with the purchase-time features and the target."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        df = con.sql(QUERY).df()
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("object")
    return df


def time_split(df: pd.DataFrame, test_share: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by purchase time: the oldest orders train the model, the newest test it.

    The frame must already be sorted by purchased_at (load_model_data does this).
    """
    cutoff = int(len(df) * (1 - test_share))
    return df.iloc[:cutoff].copy(), df.iloc[cutoff:].copy()
