"""Download the Olist Brazilian E-Commerce dataset from Kaggle into data/raw/.

If ~/.kaggle/kaggle.json exists, its username and key are used for the request.
Otherwise the script tries Kaggle's public download link, which works for
public datasets like this one. If both fail, it explains how to download the
zip by hand.
"""

import base64
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DATASET = "olistbr/brazilian-ecommerce"
DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}"
DATASET_PAGE = f"https://www.kaggle.com/datasets/{DATASET}"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
ZIP_PATH = RAW_DIR / "brazilian-ecommerce.zip"
KAGGLE_JSON = Path.home() / ".kaggle" / "kaggle.json"

EXPECTED_FILES = [
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]

MANUAL_MESSAGE = (
    "Could not download the dataset automatically.\n"
    f"Download the zip manually from the Kaggle page ({DATASET_PAGE}) "
    f"and unzip into {RAW_DIR.relative_to(PROJECT_ROOT)}/"
)


def build_request() -> urllib.request.Request:
    """Build the download request, adding basic auth if kaggle.json is present."""
    request = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "python-urllib"})
    if KAGGLE_JSON.exists():
        creds = json.loads(KAGGLE_JSON.read_text())
        token = base64.b64encode(f"{creds['username']}:{creds['key']}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
        print(f"Using Kaggle credentials from {KAGGLE_JSON}")
    else:
        print(f"No {KAGGLE_JSON} found, trying the public download link")
    return request


def download_zip() -> None:
    """Stream the dataset zip to disk."""
    with urllib.request.urlopen(build_request(), timeout=120) as response, open(ZIP_PATH, "wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    print(f"Downloaded {ZIP_PATH.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if all((RAW_DIR / name).exists() for name in EXPECTED_FILES):
        print("All 9 CSV files already exist in data/raw/, nothing to do.")
        return

    try:
        download_zip()
        with zipfile.ZipFile(ZIP_PATH) as archive:
            archive.extractall(RAW_DIR)
    except (urllib.error.URLError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        print(f"Error: {error}")
        print(MANUAL_MESSAGE)
        sys.exit(1)
    finally:
        ZIP_PATH.unlink(missing_ok=True)

    missing = [name for name in EXPECTED_FILES if not (RAW_DIR / name).exists()]
    if missing:
        print(f"The zip did not contain: {missing}")
        print(MANUAL_MESSAGE)
        sys.exit(1)

    print(f"Extracted {len(EXPECTED_FILES)} CSV files into data/raw/")


if __name__ == "__main__":
    main()
