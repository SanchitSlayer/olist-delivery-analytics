"""Label the themes of negative reviews with Gemini and compare against a keyword baseline.

Run from the project root:  python -m src.review_themes

Steps:
1. Take a fixed random sample of 400 reviews scored 1-2 that have comment text.
2. Label them with a simple Portuguese keyword baseline.
3. Write 40 of them to data/labels/hand_labels.csv for manual labelling (without any model labels).
4. If GEMINI_API_KEY is set in .env, ask Gemini for an English translation, one theme and a confidence
   for each review, in batches. Results are cached in app/data/review_themes.parquet, so a second run
   only sends reviews that are not labelled yet.
5. Print the theme distribution, the agreement with the keyword baseline, and how the
   late_delivery / not_received themes compare with the actual delivery data.
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

from src.features import DB_PATH, PROJECT_ROOT

CACHE_PATH = PROJECT_ROOT / "app" / "data" / "review_themes.parquet"
HAND_LABELS_PATH = PROJECT_ROOT / "data" / "labels" / "hand_labels.csv"

SAMPLE_SIZE = 400
HAND_LABEL_SIZE = 40
RANDOM_STATE = 42

BATCH_SIZE = 20
MAX_ATTEMPTS = 5
SECONDS_BETWEEN_CALLS = 7.0   # stays under ~10 requests a minute on the free tier
DEFAULT_MODEL = "gemini-2.5-flash"

THEMES = [
    "late_delivery",
    "not_received",
    "wrong_item",
    "damaged_or_defective",
    "poor_quality",
    "seller_communication",
    "other",
]

# Checked in this order; the first match wins. Text is lower-cased and accents are removed first.
KEYWORD_RULES = [
    ("wrong_item", [r"errad", r"diferente", r"outro produto", r"trocad", r"faltand", r"faltou", r"incomplet"]),
    ("not_received", [r"nao recebi", r"nao chegou", r"nao foi entregue", r"nao entreg", r"nao recebemos",
                      r"ainda nao", r"nao envi"]),
    ("damaged_or_defective", [r"defeito", r"quebrad", r"danificad", r"nao funciona", r"estragad", r"avariad"]),
    ("late_delivery", [r"atras", r"demor", r"prazo"]),
    ("poor_quality", [r"qualidade", r"material", r"fragil", r"fraco"]),
    ("seller_communication", [r"resposta", r"respond", r"contato", r"atendimento"]),
]

SAMPLE_QUERY = """
    select
        r.review_id,
        r.order_id,
        r.review_score,
        trim(concat_ws('. ', nullif(trim(r.comment_title), ''), trim(r.comment_message))) as comment,
        r.review_answered_at,
        f.order_status,
        f.is_delivered,
        f.is_late,
        f.days_late,
        f.estimated_delivery_date,
        f.delivered_to_customer_at
    from staging.stg_order_reviews as r
    inner join marts.fct_orders as f using (order_id)
    where r.review_score <= 2
      and r.comment_message is not null
      and trim(r.comment_message) <> ''
    order by r.review_id
"""

PROMPT = """You label customer reviews from a Brazilian online marketplace. The reviews are in Portuguese
and all of them gave the order 1 or 2 stars.

For each review return:
- "id": the id you were given, unchanged
- "english_translation": a faithful, short English translation
- "theme": the ONE main reason for the complaint, from this list:
    late_delivery         the order arrived, but later than expected or promised
    not_received          the customer says the order (or the whole order) has not arrived
    wrong_item            a different product, wrong size/colour, or only part of the order arrived
    damaged_or_defective  the product arrived broken, damaged, or does not work
    poor_quality          the product works but is worse than described or low quality
    seller_communication  no answer from the seller or the store, poor support, problems with a return or refund
    other                 none of the above, or not enough information
  If several apply, pick the one the customer is most upset about.
- "confidence": a number from 0 to 1 for how sure you are about the theme

Return only a JSON array with one object per review, in the same order as the input.

Reviews:
"""

RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "english_translation": {"type": "string"},
            "theme": {"type": "string", "enum": THEMES},
            "confidence": {"type": "number"},
        },
        "required": ["id", "english_translation", "theme", "confidence"],
    },
}


# ---------------------------------------------------------------- sample and baseline

def load_sample(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Fixed random sample of 1-2 star reviews that have comment text."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        reviews = con.sql(SAMPLE_QUERY).df()
    sample = reviews.sample(n=SAMPLE_SIZE, random_state=RANDOM_STATE)
    return sample.reset_index(drop=True)


def normalise(text: str) -> str:
    """Lower-case and strip accents, so 'não' matches 'nao'."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def keyword_theme(text: str) -> str:
    """Baseline label: the first theme whose keywords appear in the review."""
    clean = normalise(text)
    for theme, patterns in KEYWORD_RULES:
        if any(re.search(p, clean) for p in patterns):
            return theme
    return "other"


# ---------------------------------------------------------------- hand labels

def write_hand_label_sheet(sample: pd.DataFrame, labels: pd.DataFrame | None) -> None:
    """Create the hand-label CSV, or fill in missing translations without touching existing labels.

    The sheet never contains the model or keyword labels, so the manual labels stay blind.
    """
    translations = {} if labels is None else dict(zip(labels.review_id, labels.english_translation))

    if HAND_LABELS_PATH.exists():
        sheet = pd.read_csv(HAND_LABELS_PATH, dtype=str, keep_default_na=False)
        missing = sheet["english_translation"] == ""
        sheet.loc[missing, "english_translation"] = sheet.loc[missing, "review_id"].map(lambda i: translations.get(i, ""))
    else:
        picked = sample.sample(n=HAND_LABEL_SIZE, random_state=RANDOM_STATE)
        sheet = pd.DataFrame({
            "review_id": picked.review_id,
            "review_score": picked.review_score,
            "comment": picked.comment,
            "english_translation": picked.review_id.map(lambda i: translations.get(i, "")),
            "my_theme": "",
            "notes": "",
        })
    HAND_LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(HAND_LABELS_PATH, index=False)


# ---------------------------------------------------------------- Gemini labelling

def validate_batch(raw_text: str, expected_ids: list[str]) -> list[dict]:
    """Parse the model's JSON and keep only well-formed rows for ids we asked about."""
    rows = json.loads(raw_text)
    if not isinstance(rows, list):
        raise ValueError("response is not a JSON array")
    valid = []
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in expected_ids:
            continue
        if row.get("theme") not in THEMES:
            continue
        try:
            confidence = float(row.get("confidence"))
        except (TypeError, ValueError):
            continue
        valid.append({
            "review_id": row["id"],
            "english_translation": str(row.get("english_translation", "")).strip(),
            "theme": row["theme"],
            "confidence": min(max(confidence, 0.0), 1.0),
        })
    return valid


class GeminiLabeller:
    """Sends batches of reviews to Gemini with rate limiting and retries."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model
        self.last_call = 0.0

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self.last_call
        if elapsed < SECONDS_BETWEEN_CALLS:
            time.sleep(SECONDS_BETWEEN_CALLS - elapsed)
        self.last_call = time.monotonic()

    def label_batch(self, batch: pd.DataFrame) -> list[dict]:
        """Label one batch. Retries rate-limit, server and bad-JSON errors with backoff."""
        from google.genai import errors, types

        ids = batch.review_id.tolist()
        payload = json.dumps([{"id": r.review_id, "text": r.comment} for r in batch.itertuples()],
                             ensure_ascii=False)
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_for_rate_limit()
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=PROMPT + payload, config=config
                )
                return validate_batch(response.text or "", ids)
            except errors.APIError as err:
                if err.code in (400, 401, 403, 404):
                    raise  # bad key, bad model name or bad request: retrying will not help
                reason = f"API error {err.code}"
            except (json.JSONDecodeError, ValueError) as err:
                reason = f"unreadable response ({err})"
            wait = min(60, 5 * 2 ** (attempt - 1))
            print(f"  attempt {attempt} failed: {reason}; waiting {wait}s")
            time.sleep(wait)
        print(f"  giving up on this batch after {MAX_ATTEMPTS} attempts")
        return []


def load_cache() -> pd.DataFrame | None:
    return pd.read_parquet(CACHE_PATH) if CACHE_PATH.exists() else None


def label_with_gemini(sample: pd.DataFrame, labeller: GeminiLabeller) -> pd.DataFrame:
    """Label every sampled review that is not in the cache yet; save after each batch."""
    cache = load_cache()
    done = set() if cache is None else set(cache.review_id)
    todo = sample[~sample.review_id.isin(done)]
    print(f"{len(done)} reviews already labelled, {len(todo)} to go")

    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo.iloc[start:start + BATCH_SIZE]
        labels = labeller.label_batch(batch)
        print(f"  batch {start // BATCH_SIZE + 1}: {len(labels)} of {len(batch)} labelled")
        if not labels:
            continue
        new = pd.DataFrame(labels).assign(model=labeller.model)
        cache = new if cache is None else pd.concat([cache, new], ignore_index=True)
        save_labels(sample, cache)
        cache = load_cache()

    missing = len(sample) - (0 if cache is None else sample.review_id.isin(cache.review_id).sum())
    if missing:
        print(f"{missing} reviews are still unlabelled; run the script again to retry them")
    return cache


def save_labels(sample: pd.DataFrame, labels: pd.DataFrame) -> None:
    """Join the model labels to the sample (order facts and keyword theme) and write the cache."""
    keep = ["review_id", "english_translation", "theme", "confidence", "model"]
    out = sample.merge(labels[keep].drop_duplicates("review_id", keep="last"), on="review_id", how="inner")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(CACHE_PATH, index=False)


# ---------------------------------------------------------------- summary

def delivery_outcome(row) -> str:
    """What the order data says happened to this order."""
    if not row.is_delivered:
        return "not delivered"
    if row.is_late:
        return "delivered late"
    return "delivered on time"


def summarise(labelled: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Theme distribution, agreement with the keywords, and comparison with delivery data."""
    df = labelled.assign(outcome=labelled.apply(delivery_outcome, axis=1))
    df["reviewed_before_delivery"] = (
        df.is_delivered & (df.review_answered_at < df.delivered_to_customer_at)
    )

    distribution = pd.DataFrame({
        "llm_reviews": df.theme.value_counts(),
        "llm_pct": 100 * df.theme.value_counts(normalize=True),
        "keyword_reviews": df.keyword_theme.value_counts(),
        "keyword_pct": 100 * df.keyword_theme.value_counts(normalize=True),
    }).reindex(THEMES).fillna(0)

    agreement = (
        df.assign(agree=df.theme == df.keyword_theme)
        .groupby("theme")
        .agg(reviews=("agree", "size"), keyword_agrees_pct=("agree", lambda s: 100 * s.mean()))
        .reindex(THEMES)
    )

    delivery_themes = df[df.theme.isin(["late_delivery", "not_received"])]
    vs_delivery = pd.crosstab(delivery_themes.theme, delivery_themes.outcome, margins=True)
    before = delivery_themes.groupby("theme").reviewed_before_delivery.sum().rename("reviewed_before_delivery")

    return {
        "distribution": distribution,
        "agreement": agreement,
        "overall_agreement_pct": pd.DataFrame({"pct": [100 * (df.theme == df.keyword_theme).mean()]}),
        "delivery_themes_vs_order_data": vs_delivery.join(before, how="left"),
        "theme_by_outcome": pd.crosstab(df.outcome, df.theme, normalize="index").mul(100).round(1),
        "mean_confidence": df.groupby("theme").confidence.mean().reindex(THEMES).to_frame(),
    }


# ---------------------------------------------------------------- main

def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    sample = load_sample()
    sample["keyword_theme"] = sample.comment.map(keyword_theme)
    print(f"sampled {len(sample)} reviews scored 1-2 with comment text")
    print("keyword baseline themes:")
    print(sample.keyword_theme.value_counts().to_string())

    write_hand_label_sheet(sample, load_cache())
    print(f"hand-label sheet: {HAND_LABELS_PATH.relative_to(PROJECT_ROOT)}")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "\nGEMINI_API_KEY is not set, so the Gemini labelling step was skipped.\n"
            "Copy .env.example to .env, add a free key from Google AI Studio, and run this again.\n"
            "The rest of the project (dbt, notebooks, dashboard) does not need the key."
        )

    from google import genai
    from google.genai import errors

    model = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    labeller = GeminiLabeller(genai.Client(api_key=api_key), model)
    print(f"labelling with {model}")
    try:
        labels = label_with_gemini(sample, labeller)
    except errors.APIError as err:
        sys.exit(f"\nGemini rejected the request ({err.code}): {err.message}\n"
                 "Check that GEMINI_API_KEY is valid and GEMINI_MODEL is a model your key can use.")
    if labels is None:
        sys.exit("No reviews could be labelled.")

    write_hand_label_sheet(sample, labels)
    labelled = load_cache()
    for name, table in summarise(labelled).items():
        print(f"\n{name}:")
        print(table.round(1).to_string())


if __name__ == "__main__":
    main()
