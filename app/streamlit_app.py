"""Olist delivery and customer experience dashboard.

Run locally from the project root:  streamlit run app/streamlit_app.py

Reads only the parquet files in app/data/ (written by scripts/export_marts.py,
src/train_model.py and src/review_themes.py), so it runs without the warehouse.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR.parent))
from src.chart_style import BLUE, GREY, ORANGE, TEXT_MUTED, register_template  # noqa: E402

DATA_DIR = APP_DIR / "data"
REVENUE_EXCLUDED_STATUSES = ["canceled", "unavailable"]
THEME_LABELS = {
    "not_received": "Not received",
    "wrong_item": "Wrong or incomplete item",
    "poor_quality": "Poor quality",
    "damaged_or_defective": "Damaged or defective",
    "seller_communication": "Seller communication",
    "late_delivery": "Late delivery",
    "other": "Other",
}

st.set_page_config(page_title="Olist delivery analytics", layout="wide")
register_template()


# ---------------------------------------------------------------- data

@st.cache_data
def load_orders() -> pd.DataFrame:
    orders = pd.read_parquet(DATA_DIR / "orders.parquet")
    orders["purchase_date"] = orders["purchased_at"].dt.date
    orders["month"] = orders["purchased_at"].dt.to_period("M").dt.to_timestamp()
    return orders


@st.cache_data
def load_optional(name: str) -> pd.DataFrame | None:
    """Load a parquet file that may not exist yet (the model and LLM steps are optional)."""
    path = DATA_DIR / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else None


def apply_filters(df: pd.DataFrame, date_col: str, start, end, states: list[str]) -> pd.DataFrame:
    dates = df[date_col].dt.date
    mask = (dates >= start) & (dates <= end)
    if states:
        mask &= df["customer_state"].isin(states)
    return df[mask]


# ---------------------------------------------------------------- helpers

def chart(fig: go.Figure, height: int = 380) -> None:
    fig.update_layout(height=height, margin=dict(l=50, r=20, t=60, b=40))
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    st.plotly_chart(fig, theme=None, width="stretch", config={"displayModeBar": False})


def pct(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{100 * x:.1f}%"


def late_rate(df: pd.DataFrame) -> float:
    delivered = df[df.is_delivered]
    return delivered.is_late.mean() if len(delivered) else np.nan


def gains_curve(y_true: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cumulative % of late orders caught as more of the riskiest orders are reviewed."""
    order = np.argsort(-scores, kind="stable")
    caught = np.cumsum(y_true[order]) / max(y_true.sum(), 1)
    reviewed = np.arange(1, len(order) + 1) / len(order)
    return 100 * reviewed, 100 * caught


def roc_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """ROC-AUC from ranks (Mann-Whitney), so the app does not need scikit-learn."""
    n_pos, n_neg = y_true.sum(), len(y_true) - y_true.sum()
    if n_pos == 0 or n_neg == 0:
        return np.nan
    ranks = pd.Series(scores).rank().to_numpy()
    return (ranks[y_true == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


# ---------------------------------------------------------------- sidebar filters

orders_all = load_orders()
scores_all = load_optional("late_risk_scores")
themes_all = load_optional("review_themes")

st.sidebar.header("Filters")
min_date, max_date = orders_all.purchase_date.min(), orders_all.purchase_date.max()
date_range = st.sidebar.date_input(
    "Purchase date",
    value=(pd.Timestamp("2017-01-01").date(), pd.Timestamp("2018-08-31").date()),
    min_value=min_date,
    max_value=max_date,
)
start, end = date_range if len(date_range) == 2 else (date_range[0], max_date)
states = st.sidebar.multiselect(
    "Customer state", sorted(orders_all.customer_state.dropna().unique()),
    placeholder="All states",
)
st.sidebar.caption(
    "Default range is January 2017 to August 2018; the months before and after have very few orders. "
    "Late = delivered on a later date than promised at purchase."
)

orders = apply_filters(orders_all, "purchased_at", start, end, states)
delivered = orders[orders.is_delivered]

st.title("Olist delivery and customer experience")
st.caption(
    f"{len(orders):,} orders from {start:%d %b %Y} to {end:%d %b %Y}"
    + (f" for {', '.join(states)}" if states else ", all states")
    + ". Data: Olist Brazilian e-commerce public dataset (Kaggle, CC BY-NC-SA 4.0)."
)

if orders.empty:
    st.warning("No orders match these filters.")
    st.stop()

tab_overview, tab_delivery, tab_sellers, tab_model, tab_complaints = st.tabs(
    ["Overview", "Delivery & Reviews", "Sellers", "Late-Risk Model", "Customer Complaints"]
)


# ---------------------------------------------------------------- overview

with tab_overview:
    revenue = orders.loc[~orders.order_status.isin(REVENUE_EXCLUDED_STATUSES), "order_value"].sum()
    cols = st.columns(6)
    cols[0].metric("Orders", f"{len(orders):,}")
    cols[1].metric("Revenue", f"R$ {revenue / 1e6:,.1f}M", help="Items plus freight, excluding canceled and unavailable orders")
    cols[2].metric("Delivered", f"{len(delivered):,}")
    cols[3].metric("Late rate", pct(late_rate(orders)), help="Share of delivered orders that arrived after the promised date")
    cols[4].metric("Average review", f"{orders.review_score.mean():.2f}")
    cols[5].metric("Median delivery days", f"{delivered.delivery_days.median():.0f}")

    monthly = orders.groupby("month").agg(
        orders=("order_id", "size"),
        delivered=("is_delivered", "sum"),
        late=("is_late", "sum"),
        avg_review=("review_score", "mean"),
    ).reset_index()
    monthly["late_pct"] = 100 * monthly.late / monthly.delivered.replace(0, np.nan)

    left, right = st.columns(2)
    with left:
        fig = go.Figure(go.Bar(x=monthly.month, y=monthly.orders, marker_color=BLUE,
                               hovertemplate="%{x|%b %Y}: %{y:,} orders<extra></extra>"))
        fig.update_layout(title="Orders per month", yaxis_title="Orders")
        chart(fig)
    with right:
        fig = go.Figure(go.Scatter(x=monthly.month, y=monthly.late_pct, mode="lines+markers",
                                   line_color=ORANGE, hovertemplate="%{x|%b %Y}: %{y:.1f}% late<extra></extra>"))
        fig.update_layout(title="Late deliveries per month", yaxis_title="Late (% of delivered)",
                          yaxis_rangemode="tozero")
        chart(fig)

    fig = go.Figure(go.Scatter(x=monthly.month, y=monthly.avg_review, mode="lines+markers", line_color=BLUE,
                               hovertemplate="%{x|%b %Y}: %{y:.2f}<extra></extra>"))
    fig.update_layout(title="Average review score per month", yaxis_title="Average review (1-5)",
                      yaxis_range=[1, 5])
    chart(fig, height=320)
    st.caption("Late deliveries and review scores move in opposite directions: the late-rate peaks in "
               "November 2017 and February to March 2018 line up with the dips in review score.")


# ---------------------------------------------------------------- delivery and reviews

with tab_delivery:
    reviewed = delivered.dropna(subset=["review_score"]).copy()
    reviewed["delivery"] = np.where(reviewed.is_late, "Late", "On time")
    buckets = pd.cut(reviewed.days_late.where(reviewed.is_late, 0), [-1, 0, 3, 7, 14, 10_000],
                     labels=["On time", "1-3", "4-7", "8-14", "15+"])

    left, right = st.columns(2)
    with left:
        by_bucket = reviewed.groupby(buckets, observed=True).review_score.agg(["mean", "size"]).reset_index()
        colours = [BLUE] + [ORANGE] * (len(by_bucket) - 1)
        fig = go.Figure(go.Bar(
            x=by_bucket.days_late, y=by_bucket["mean"], marker_color=colours,
            text=by_bucket["mean"].map("{:.2f}".format), textposition="outside",
            customdata=by_bucket["size"], hovertemplate="%{x}: %{y:.2f} (%{customdata:,} reviews)<extra></extra>",
        ))
        fig.update_layout(title="Average review by how late the order was", xaxis_title="Days late",
                          yaxis_title="Average review (1-5)", yaxis_range=[0, 5.4])
        chart(fig)
    with right:
        dist = (reviewed.groupby("delivery").review_score.value_counts(normalize=True)
                .mul(100).rename("pct").reset_index())
        fig = go.Figure()
        for label, colour in [("On time", BLUE), ("Late", ORANGE)]:
            part = dist[dist.delivery == label].sort_values("review_score")
            fig.add_bar(x=part.review_score, y=part.pct, name=label, marker_color=colour,
                        hovertemplate="%{x} stars: %{y:.1f}%<extra>" + label + "</extra>")
        fig.update_layout(title="Review score distribution", xaxis_title="Stars", yaxis_title="% of reviews",
                          barmode="group", xaxis=dict(tickmode="linear"))
        chart(fig)

    by_state = (delivered.groupby("customer_state")
                .agg(delivered=("is_late", "size"), late=("is_late", "sum")).reset_index())
    by_state = by_state[by_state.delivered >= 100]
    by_state["late_pct"] = 100 * by_state.late / by_state.delivered
    by_state = by_state.sort_values("late_pct")
    overall = 100 * late_rate(orders)

    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure(go.Bar(
            y=by_state.customer_state, x=by_state.late_pct, orientation="h",
            marker_color=np.where(by_state.late_pct > overall, ORANGE, GREY),
            text=by_state.late_pct.map("{:.1f}%".format), textposition="outside",
            customdata=by_state[["delivered", "late"]],
            hovertemplate="%{y}: %{x:.1f}% late (%{customdata[1]:,} of %{customdata[0]:,})<extra></extra>",
        ))
        fig.update_layout(title=f"Late rate by customer state (orange = above the {overall:.1f}% average)",
                          xaxis_title="Late (% of delivered)", yaxis=dict(dtick=1),
                          xaxis_range=[0, by_state.late_pct.max() * 1.15])
        chart(fig, height=max(320, 22 * len(by_state) + 100))
        st.caption("States with at least 100 delivered orders in the selection.")
    with right:
        st.markdown("**Seller-to-customer routes with the highest late rate**")
        min_route = st.slider("Minimum delivered orders per route", 20, 500, 100, step=10)
        routes = (delivered.groupby(["seller_state", "customer_state"])
                  .agg(delivered=("is_late", "size"), late=("is_late", "sum")).reset_index())
        routes = routes[routes.delivered >= min_route]
        routes["late_rate"] = 100 * routes.late / routes.delivered
        routes["route"] = routes.seller_state + " → " + routes.customer_state
        st.dataframe(
            routes.sort_values("late_rate", ascending=False)[["route", "delivered", "late", "late_rate"]].head(15),
            hide_index=True, width="stretch",
            column_config={"late_rate": st.column_config.NumberColumn("late %", format="%.1f")},
        )


# ---------------------------------------------------------------- sellers

with tab_sellers:
    sellers = (delivered.groupby(["seller_id", "seller_state"])
               .agg(delivered=("is_late", "size"), late=("is_late", "sum"),
                    avg_review=("review_score", "mean"), revenue=("order_value", "sum"))
               .reset_index())
    sellers["late_rate"] = sellers.late / sellers.delivered

    ranked = sellers.sort_values("late", ascending=False).reset_index(drop=True)
    total_late = ranked.late.sum()
    if total_late == 0:
        st.info("No late orders in this selection.")
    else:
        cum_late = 100 * ranked.late.cumsum() / total_late
        cum_sellers = 100 * (np.arange(len(ranked)) + 1) / len(ranked)
        sellers_for_half = int((cum_late < 50).sum() + 1)

        cols = st.columns(3)
        cols[0].metric("Sellers with delivered orders", f"{len(sellers):,}")
        cols[1].metric("Sellers behind half of late orders", f"{sellers_for_half:,}",
                       help="Sellers ranked by number of late orders")
        cols[2].metric("Share of sellers", f"{100 * sellers_for_half / len(sellers):.1f}%")

        left, right = st.columns([2, 3])
        with left:
            fig = go.Figure(go.Scatter(x=cum_sellers, y=cum_late, mode="lines", line_color=ORANGE,
                                       hovertemplate="top %{x:.1f}% of sellers: %{y:.1f}% of late orders<extra></extra>"))
            fig.add_hline(y=50, line_color=GREY, line_dash="dot")
            fig.update_layout(title="Cumulative share of late orders by seller",
                              xaxis_title="Sellers, ranked by late orders (%)", yaxis_title="Late orders (%)",
                              yaxis_range=[0, 102])
            chart(fig)
        with right:
            min_orders = st.slider("Minimum delivered orders per seller", 10, 500, 50, step=10)
            table = sellers[sellers.delivered >= min_orders].sort_values("late", ascending=False).head(20).copy()
            table["seller"] = table.seller_id.str[:8]
            st.markdown(f"**Top sellers by number of late orders** (at least {min_orders} delivered)")
            st.dataframe(
                table[["seller", "seller_state", "delivered", "late", "late_rate", "avg_review", "revenue"]],
                hide_index=True, width="stretch",
                column_config={
                    "seller_state": st.column_config.TextColumn("state"),
                    "late_rate": st.column_config.NumberColumn("late rate", format="percent"),
                    "avg_review": st.column_config.NumberColumn("avg review", format="%.2f"),
                    "revenue": st.column_config.NumberColumn("revenue (R$)", format="%,.0f"),
                },
            )
            st.caption("Seller ids are shortened to the first 8 characters. Each order is credited to its "
                       "main seller (highest item value).")


# ---------------------------------------------------------------- late-risk model

with tab_model:
    if scores_all is None:
        st.info("No model scores yet. Run `python -m src.train_model` to create app/data/late_risk_scores.parquet.")
    else:
        st.caption(
            "Logistic regression trained on orders up to 26 May 2018 and scored on the newest 20% of delivered "
            "orders (26 May to 29 Aug 2018), using only information known at purchase. The date and state "
            "filters apply within that test period."
        )
        scores = apply_filters(scores_all, "purchased_at", start, end, states)
        if scores.empty:
            st.info("No scored orders in this selection. The model was tested on orders from 26 May to "
                    "29 Aug 2018, so include part of that period in the date filter.")
        elif scores.is_late.sum() == 0:
            st.info(f"The {len(scores):,} scored orders in this selection include no late orders, "
                    "so there is nothing to measure.")
        else:
            share = st.slider("Share of orders the operations team reviews (riskiest first)", 5, 30, 10, step=5)
            y = scores.is_late.to_numpy().astype(int)
            s = scores.risk_score.to_numpy()
            n_flag = max(1, int(round(len(y) * share / 100)))
            top = np.argsort(-s, kind="stable")[:n_flag]
            caught = y[top].sum() / y.sum()

            cols = st.columns(5)
            cols[0].metric("Orders scored", f"{len(y):,}")
            cols[1].metric("Late orders", f"{y.sum():,}", help=f"{pct(y.mean())} of scored orders")
            cols[2].metric(f"Late orders caught in top {share}%", pct(caught))
            cols[3].metric("vs random", f"{caught / (share / 100):.1f}x")
            cols[4].metric("ROC-AUC", f"{roc_auc(y, s):.2f}")

            left, right = st.columns([3, 2])
            with left:
                x_curve, y_curve = gains_curve(y, s)
                step = max(1, len(x_curve) // 400)
                fig = go.Figure()
                fig.add_scatter(x=x_curve[::step], y=y_curve[::step], mode="lines", line_color=BLUE, name="Model",
                                hovertemplate="review %{x:.0f}%: catch %{y:.0f}% of late orders<extra></extra>")
                fig.add_scatter(x=[0, 100], y=[0, 100], mode="lines", name="Random",
                                line=dict(color=GREY, dash="dot"), hoverinfo="skip")
                fig.add_vline(x=share, line_color=TEXT_MUTED, line_width=1, line_dash="dot")
                fig.add_scatter(x=[share], y=[100 * caught], mode="markers", showlegend=False, hoverinfo="skip",
                                marker=dict(color=BLUE, size=10, line=dict(color="white", width=2)))
                fig.update_layout(title="Late orders caught vs orders reviewed",
                                  xaxis_title="Riskiest orders reviewed (%)", yaxis_title="Late orders caught (%)",
                                  xaxis_range=[0, 100], yaxis_range=[0, 102])
                chart(fig)
            with right:
                st.markdown("**What drives the risk score**")
                st.markdown(
                    "1. **Promised delivery time**: by far the strongest signal. Short promises are missed "
                    "much more often.\n"
                    "2. **Seller state**: where the parcel starts (Maranhão and São Paulo sellers score higher).\n"
                    "3. **Customer state**: where it goes (Northeast and North states score higher).\n"
                    "4. **Number of items**: multi-item orders are slightly less risky.\n"
                    "5. **Purchase month**: peak months (Nov, Feb, Mar) raise the score; little effect in this "
                    "test period."
                )
                st.caption("From permutation importance on the test period. Details: reports/model_results.md. "
                           "Scores rank orders; they are not calibrated probabilities.")

            st.markdown(f"**Riskiest orders in the selection** (top {min(n_flag, 25)} of {n_flag:,} flagged)")
            flagged = scores.iloc[top[:25]].copy()
            flagged["order"] = flagged.order_id.str[:8]
            flagged["route"] = flagged.seller_state + " → " + flagged.customer_state
            st.dataframe(
                flagged[["order", "purchased_at", "route", "main_category", "promised_days", "risk_score", "is_late"]],
                hide_index=True, width="stretch",
                column_config={
                    "purchased_at": st.column_config.DatetimeColumn("purchased", format="YYYY-MM-DD"),
                    "main_category": st.column_config.TextColumn("category"),
                    "promised_days": st.column_config.NumberColumn("promised days"),
                    "risk_score": st.column_config.NumberColumn("risk score", format="%.2f"),
                    "is_late": st.column_config.CheckboxColumn("was late"),
                },
            )


# ---------------------------------------------------------------- customer complaints

with tab_complaints:
    if themes_all is None:
        st.info("No review themes yet. Add a Gemini key to .env and run `python -m src.review_themes`.")
    else:
        themes = themes_all.merge(orders_all[["order_id", "purchased_at", "customer_state"]], on="order_id")
        themes = apply_filters(themes, "purchased_at", start, end, states)
        st.caption(
            f"A random sample of 1-2 star reviews with comments, labelled by {themes_all.model.iloc[0]} "
            f"({len(themes_all)} reviews in total, {len(themes)} in the current selection). "
            "Each review gets one main theme."
        )
        if len(themes) < 30:
            st.warning("Fewer than 30 labelled reviews match the filters, so these shares are very rough.")
        if not themes.empty:
            themes = themes.assign(
                theme_label=themes.theme.map(THEME_LABELS),
                outcome=np.select(
                    [~themes.is_delivered, themes.is_late.fillna(False)],
                    ["Not delivered", "Delivered late"], default="Delivered on time",
                ),
            )
            left, right = st.columns(2)
            with left:
                counts = themes.theme_label.value_counts().sort_values()
                fig = go.Figure(go.Bar(
                    y=counts.index, x=100 * counts / counts.sum(), orientation="h", marker_color=BLUE,
                    text=[f"{100 * c / counts.sum():.0f}%" for c in counts], textposition="outside",
                    customdata=counts, hovertemplate="%{y}: %{x:.1f}% (%{customdata} reviews)<extra></extra>",
                ))
                fig.update_layout(title="Main complaint in 1-2 star reviews", xaxis_title="% of reviews",
                                  xaxis_range=[0, 100 * counts.max() / counts.sum() * 1.18])
                chart(fig)
            with right:
                # Share of each outcome's reviews per theme (columns sum to 100%).
                mix = pd.crosstab(themes.theme_label, themes.outcome, normalize="columns").mul(100)
                mix = mix.reindex([THEME_LABELS[t] for t in THEME_LABELS if THEME_LABELS[t] in mix.index])
                mix = mix[[c for c in ["Delivered on time", "Delivered late", "Not delivered"] if c in mix]]
                fig = go.Figure(go.Heatmap(
                    z=mix.values, x=mix.columns, y=mix.index, colorscale=[[0, "#f3f2ee"], [1, BLUE]],
                    zmin=0, zmax=70, text=mix.round(0).astype(int).astype(str) + "%", texttemplate="%{text}",
                    hovertemplate="%{x}, %{y}: %{z:.1f}%<extra></extra>", showscale=False, xgap=2, ygap=2,
                ))
                fig.update_layout(title="Complaint mix by delivery outcome (columns add to 100%)",
                                  yaxis=dict(autorange="reversed"), xaxis=dict(side="top", title=None))
                chart(fig)
            st.caption("Reviews on late orders are mostly about delivery. Reviews on on-time orders are mostly "
                       "about the product, and many 'wrong item' complaints are items missing from multi-item orders.")

            theme_choice = st.selectbox("Read reviews for a theme", list(THEME_LABELS.values()))
            sample = themes[themes.theme_label == theme_choice]
            st.dataframe(
                sample[["review_score", "outcome", "english_translation", "comment", "confidence"]],
                hide_index=True, width="stretch",
                column_config={
                    "review_score": st.column_config.NumberColumn("stars"),
                    "english_translation": st.column_config.TextColumn("English translation", width="large"),
                    "comment": st.column_config.TextColumn("original (Portuguese)", width="medium"),
                    "confidence": st.column_config.NumberColumn(format="%.2f"),
                },
            )
