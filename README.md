# E-commerce Delivery & Customer Experience Analytics

Work in progress. The full write-up comes at the end of the project.

## Setup

Requires Python 3.11.

Mac / Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Get the data

```bash
python scripts/download_data.py
python scripts/load_raw.py
```

`download_data.py` uses `~/.kaggle/kaggle.json` if present, otherwise Kaggle's public download link. If both fail, download the zip from the [Kaggle dataset page](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and unzip it into `data/raw/`.

`load_raw.py` loads the 9 CSV files into `warehouse/olist.duckdb` under the `raw` schema.
