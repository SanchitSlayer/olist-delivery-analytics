"""Load the 9 Olist CSV files into the DuckDB warehouse under the "raw" schema.

Each table is replaced on every run, so the script is safe to re-run.
Columns are loaded as text (all_varchar) so that nothing is silently coerced
at this stage; type casting happens in the dbt staging models.
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
WAREHOUSE_PATH = PROJECT_ROOT / "warehouse" / "olist.duckdb"

# raw table name -> source csv file
TABLES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def main() -> None:
    missing = [f for f in TABLES.values() if not (RAW_DIR / f).exists()]
    if missing:
        raise SystemExit(f"Missing files in data/raw/: {missing}. Run scripts/download_data.py first.")

    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE_PATH))
    con.execute("create schema if not exists raw")

    print(f"Loading into {WAREHOUSE_PATH.relative_to(PROJECT_ROOT)}\n")
    for table, filename in TABLES.items():
        csv_path = (RAW_DIR / filename).as_posix().replace("'", "''")
        con.execute(
            f"""
            create or replace table raw.{table} as
            select * from read_csv('{csv_path}', header = true, all_varchar = true)
            """
        )
        row_count = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
        print(f"raw.{table:<22} {row_count:>9,} rows")

    con.close()


if __name__ == "__main__":
    main()
