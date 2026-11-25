"""Compare my hand labels with the Gemini labels and the keyword baseline.

Fill in the my_theme column of data/labels/hand_labels.csv (one of the themes listed in
src/review_themes.py), then run from the project root:

    python scripts/score_hand_labels.py
"""

import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, cohen_kappa_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.review_themes import CACHE_PATH, HAND_LABELS_PATH, THEMES, keyword_theme  # noqa: E402


def main() -> None:
    if not HAND_LABELS_PATH.exists():
        sys.exit("No hand-label sheet yet. Run `python -m src.review_themes` first.")
    sheet = pd.read_csv(HAND_LABELS_PATH, dtype=str, keep_default_na=False)
    sheet["my_theme"] = sheet["my_theme"].str.strip().str.lower()

    labelled = sheet[sheet.my_theme != ""]
    unknown = sorted(set(labelled.my_theme) - set(THEMES))
    if unknown:
        sys.exit(f"Unknown themes in my_theme: {unknown}. Use one of: {', '.join(THEMES)}")
    if labelled.empty:
        sys.exit(f"No rows labelled yet in {HAND_LABELS_PATH.relative_to(PROJECT_ROOT)} (my_theme is empty).")
    print(f"{len(labelled)} of {len(sheet)} reviews hand-labelled")

    labelled = labelled.assign(keyword_theme=labelled.comment.map(keyword_theme))
    results = {"keyword baseline": labelled.keyword_theme}

    if CACHE_PATH.exists():
        llm = pd.read_parquet(CACHE_PATH, columns=["review_id", "theme"])
        labelled = labelled.merge(llm, on="review_id", how="left")
        if labelled.theme.isna().any():
            print(f"{labelled.theme.isna().sum()} hand-labelled reviews have no Gemini label; they count as wrong")
        results["gemini"] = labelled.theme.fillna("missing")
    else:
        print("No Gemini labels found (app/data/review_themes.parquet), so only the keyword baseline is scored.")

    print(f"\n{'labeller':<18}{'accuracy':>10}{'kappa':>8}")
    for name, predicted in results.items():
        acc = accuracy_score(labelled.my_theme, predicted)
        kappa = cohen_kappa_score(labelled.my_theme, predicted)
        print(f"{name:<18}{acc:>10.1%}{kappa:>8.2f}")

    if "gemini" in results:
        print("\nConfusion (rows = my label, columns = Gemini):")
        print(pd.crosstab(labelled.my_theme, results["gemini"]).to_string())
        wrong = labelled[labelled.my_theme != results["gemini"]]
        if not wrong.empty:
            print("\nDisagreements:")
            for row in wrong.itertuples():
                print(f"- {row.review_id[:8]}  mine={row.my_theme}  gemini={row.theme}  | {row.comment[:90]}")


if __name__ == "__main__":
    main()
