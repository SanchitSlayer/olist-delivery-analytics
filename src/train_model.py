"""Train and evaluate the late-delivery risk models.

Run from the project root:  python -m src.train_model

Trains a logistic regression baseline and a gradient boosting model on the older
80% of delivered orders, picks one on a validation slice, scores the newest 20%,
prints the metrics and writes the scored test set to app/data/late_risk_scores.parquet
for the dashboard.
"""

from itertools import product

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, OrdinalEncoder, StandardScaler

from src.features import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    PROJECT_ROOT,
    TARGET,
    load_model_data,
    time_split,
)

SCORES_PATH = PROJECT_ROOT / "app" / "data" / "late_risk_scores.parquet"
REVIEW_SHARE = 0.10  # the operations team reviews the riskiest 10% of orders
RANDOM_STATE = 42

# Small grid for the gradient boosting model, checked on a time-based validation slice.
GB_GRID = {
    "learning_rate": [0.05, 0.1],
    "max_leaf_nodes": [15, 31],
    "min_samples_leaf": [50, 200],
}


def build_logistic_regression() -> Pipeline:
    """Baseline: one-hot categories, log-scaled numbers, class-weighted logistic regression."""
    numeric = make_pipeline(
        SimpleImputer(strategy="median"),
        FunctionTransformer(np.log1p, feature_names_out="one-to-one"),  # sizes and prices are right-skewed
        StandardScaler(),
    )
    categorical = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=30)
    preprocess = ColumnTransformer([
        ("num", numeric, NUMERIC_FEATURES),
        ("cat", categorical, CATEGORICAL_FEATURES),
    ])
    model = LogisticRegression(class_weight="balanced", max_iter=2000)
    return Pipeline([("prep", preprocess), ("model", model)])


def build_gradient_boosting(**params) -> Pipeline:
    """Gradient boosting with native categorical splits and class weighting."""
    categorical = OrdinalEncoder(
        handle_unknown="use_encoded_value", unknown_value=np.nan, encoded_missing_value=np.nan
    )
    preprocess = ColumnTransformer([
        ("cat", categorical, CATEGORICAL_FEATURES),
        ("num", "passthrough", NUMERIC_FEATURES),
    ])
    is_categorical = [True] * len(CATEGORICAL_FEATURES) + [False] * len(NUMERIC_FEATURES)
    model = HistGradientBoostingClassifier(
        categorical_features=is_categorical,
        class_weight="balanced",
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=20,
        random_state=RANDOM_STATE,
        **params,
    )
    return Pipeline([("prep", preprocess), ("model", model)])


def capture_rate(y_true, scores, share: float = REVIEW_SHARE) -> float:
    """Share of all late orders that fall inside the top `share` of orders by risk score."""
    y_true = np.asarray(y_true)
    n_flagged = int(round(len(y_true) * share))
    top = np.argsort(-np.asarray(scores), kind="stable")[:n_flagged]
    return y_true[top].sum() / y_true.sum()


def evaluate(y_true, scores) -> dict:
    """Ranking metrics plus the review-the-top-10% business metric."""
    y_true = np.asarray(y_true)
    n_flagged = int(round(len(y_true) * REVIEW_SHARE))
    top = np.argsort(-np.asarray(scores), kind="stable")[:n_flagged]
    return {
        "roc_auc": roc_auc_score(y_true, scores),
        "pr_auc": average_precision_score(y_true, scores),
        "late_caught_in_top_10pct": capture_rate(y_true, scores),
        "late_rate_in_top_10pct": y_true[top].mean(),
        "base_late_rate": y_true.mean(),
    }


def choose_gb_params(fit_part: pd.DataFrame, valid_part: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Try each gradient boosting setting in GB_GRID and rank them by validation PR-AUC."""
    rows = []
    for lr, leaves, min_leaf in product(*GB_GRID.values()):
        params = {"learning_rate": lr, "max_leaf_nodes": leaves, "min_samples_leaf": min_leaf}
        model = build_gradient_boosting(**params).fit(fit_part[FEATURES], fit_part[TARGET])
        scores = model.predict_proba(valid_part[FEATURES])[:, 1]
        rows.append({**params, **evaluate(valid_part[TARGET], scores)})
    results = pd.DataFrame(rows).sort_values("pr_auc", ascending=False).reset_index(drop=True)
    best = results.iloc[0][list(GB_GRID)].to_dict()
    best["max_leaf_nodes"] = int(best["max_leaf_nodes"])
    best["min_samples_leaf"] = int(best["min_samples_leaf"])
    return best, results


def shortest_promise_first(df: pd.DataFrame) -> np.ndarray:
    """One-line rule for comparison: the shorter the promised delivery time, the riskier."""
    return -df["promised_days"].to_numpy(dtype=float)


def comparison_table(y_true, model_scores: dict, rule_scores: np.ndarray) -> pd.DataFrame:
    """Metrics for each model next to the simple rule and a random ordering."""
    table = pd.DataFrame({name: evaluate(y_true, s) for name, s in model_scores.items()}).T
    table.loc["shortest_promise_first"] = evaluate(y_true, rule_scores)
    base = float(np.mean(y_true))
    table.loc["random_ordering"] = {
        "roc_auc": 0.5,
        "pr_auc": base,
        "late_caught_in_top_10pct": REVIEW_SHARE,
        "late_rate_in_top_10pct": base,
        "base_late_rate": base,
    }
    return table


def run() -> dict:
    """Train both models, pick one on validation data and score the test period.

    The test period (newest 20% of orders) is only used once, at the very end. Model
    settings and the choice between the two models are made on a validation slice:
    the newest 20% of the training period.
    """
    df = load_model_data()
    train, test = time_split(df, test_share=0.2)
    fit_part, valid_part = time_split(train, test_share=0.2)

    # Step 1: choose settings and the final model on the validation slice.
    best_params, tuning = choose_gb_params(fit_part, valid_part)
    candidates = {
        "logistic_regression": build_logistic_regression(),
        "gradient_boosting": build_gradient_boosting(**best_params),
    }
    valid_scores = {
        name: model.fit(fit_part[FEATURES], fit_part[TARGET]).predict_proba(valid_part[FEATURES])[:, 1]
        for name, model in candidates.items()
    }
    validation = comparison_table(valid_part[TARGET], valid_scores, shortest_promise_first(valid_part))
    selected = validation.loc[list(candidates), "pr_auc"].idxmax()

    # Step 2: refit on the full training period and score the untouched test period.
    models = {
        "logistic_regression": build_logistic_regression().fit(train[FEATURES], train[TARGET]),
        "gradient_boosting": build_gradient_boosting(**best_params).fit(train[FEATURES], train[TARGET]),
    }
    scores = {name: m.predict_proba(test[FEATURES])[:, 1] for name, m in models.items()}
    metrics = comparison_table(test[TARGET], scores, shortest_promise_first(test))

    return {
        "data": df,
        "train": train,
        "test": test,
        "fit_part": fit_part,
        "valid_part": valid_part,
        "models": models,
        "scores": scores,
        "metrics": metrics,
        "validation": validation,
        "selected_model": selected,
        "best_params": best_params,
        "tuning": tuning,
    }


def scored_test_set(test: pd.DataFrame, scores: np.ndarray) -> pd.DataFrame:
    """Test orders with their risk score, risk percentile and whether they would be flagged."""
    out = test[["order_id", "purchased_at", "customer_state", "seller_state", "main_category",
                "promised_days", "items_value", "freight_value", TARGET]].copy()
    out["risk_score"] = scores
    # 1.0 = riskiest order in the test period
    out["risk_percentile"] = out["risk_score"].rank(pct=True, method="first")
    out["flagged_top_10pct"] = out["risk_percentile"] > 1 - REVIEW_SHARE
    return out.sort_values("risk_score", ascending=False).reset_index(drop=True)


def main() -> None:
    results = run()
    train, test = results["train"], results["test"]
    print(f"train: {len(train):,} orders, {train.purchased_at.min():%Y-%m-%d} to "
          f"{train.purchased_at.max():%Y-%m-%d}, late rate {train[TARGET].mean():.2%}")
    print(f"test:  {len(test):,} orders, {test.purchased_at.min():%Y-%m-%d} to "
          f"{test.purchased_at.max():%Y-%m-%d}, late rate {test[TARGET].mean():.2%}")
    print(f"gradient boosting settings: {results['best_params']}")
    print("\nvalidation slice (used to choose the model):")
    print(results["validation"].round(4).to_string())
    print(f"selected model: {results['selected_model']}")
    print("\ntest period:")
    print(results["metrics"].round(4).to_string())

    scored = scored_test_set(test, results["scores"][results["selected_model"]])
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(SCORES_PATH, index=False)
    print(f"wrote {len(scored):,} scored orders to {SCORES_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
