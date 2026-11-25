"""Export the dbt marts the dashboard needs to small parquet files in app/data/.

Run from the project root after `dbt build`:  python scripts/export_marts.py

The dashboard reads only from app/data/, so it can be deployed without the DuckDB file
(which is built locally and not committed).
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "warehouse" / "olist.duckdb"
OUT_DIR = PROJECT_ROOT / "app" / "data"
SIZE_LIMIT_MB = 20

EXPORTS = {
    # One row per order: everything the Overview, Delivery & Reviews and Sellers tabs filter and aggregate.
    "orders": """
        select
            order_id,
            purchased_at,
            order_status,
            customer_state,
            seller_state,
            main_seller_id                        as seller_id,
            main_category                         as category,
            cast(order_value as double)           as order_value,
            cast(freight_value as double)         as freight_value,
            item_count,
            is_delivered,
            is_late,
            promised_days,
            delivery_days,
            days_late,
            review_score
        from marts.fct_orders
        order by purchased_at
    """,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for name, query in EXPORTS.items():
            path = OUT_DIR / f"{name}.parquet"
            df = con.sql(query).df()
            df.to_parquet(path, index=False, compression="zstd")
            print(f"{path.relative_to(PROJECT_ROOT)}: {len(df):,} rows, {path.stat().st_size / 1e6:.1f} MB")

    total_mb = sum(p.stat().st_size for p in OUT_DIR.glob("*.parquet")) / 1e6
    print(f"app/data total: {total_mb:.1f} MB")
    if total_mb > SIZE_LIMIT_MB:
        raise SystemExit(f"app/data is over {SIZE_LIMIT_MB} MB; trim the exports before committing.")


if __name__ == "__main__":
    main()
