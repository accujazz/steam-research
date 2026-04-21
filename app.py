import io
import logging
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from calculator import (
    DEFAULT_REGIONAL_COEFF,
    DEFAULT_REVIEWS_MULTIPLIER,
    DEFAULT_SALES_COEFF,
    DEFAULT_STEAM_CUT,
    DEFAULT_TAXES,
    DEFAULT_WISHLIST_COEFF,
    compute_quartiles,
    enrich_records,
    to_dataframe,
)
from fetcher import (
    discover_apps,
    enrich_apps,
    list_cache_files,
    load_cache,
    save_cache,
)

logging.basicConfig(level=logging.WARNING)

st.set_page_config(layout="wide", page_title="Steam Genre Research")


def _run_label(filepath: str) -> str:
    """cache/roguelite_20260420.json → 'roguelite · 2026-04-20'"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    parts = base.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        d = parts[1]
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return f"{parts[0]} · {date_str}"
    return base


# ── Auto-load from query param ────────────────────────────────────────────────

qp_run = st.query_params.get("run")
if qp_run and "records" not in st.session_state:
    try:
        st.session_state["records"] = load_cache(qp_run)
        st.session_state["active_run"] = qp_run
    except Exception:
        st.query_params.clear()

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    # ── Previous runs ──
    cache_files = list_cache_files()
    if cache_files:
        st.header("Previous Runs")
        recent, older = cache_files[:10], cache_files[10:]
        for cf in recent:
            if st.button(_run_label(cf), key=f"run_{cf}", use_container_width=True):
                st.session_state["records"] = load_cache(cf)
                st.session_state["active_run"] = cf
                st.query_params["run"] = cf
                st.rerun()
        if older:
            with st.expander(f"{len(older)} older runs"):
                for cf in older:
                    if st.button(_run_label(cf), key=f"run_{cf}", use_container_width=True):
                        st.session_state["records"] = load_cache(cf)
                        st.session_state["active_run"] = cf
                        st.query_params["run"] = cf
                        st.rerun()
        st.divider()

    # ── Data source ──
    st.header("Data Source")
    mode = st.radio("Input mode", ["Manual App IDs", "Tag Discovery"])

    if mode == "Tag Discovery":
        tags_input = st.text_input("Tags (comma-separated)", "Roguelite")
        logic = st.radio("Tag logic", ["AND", "OR"])
        max_results = st.number_input("Max games to fetch", 10, 2000, 50, step=10)
        slug_input = st.text_input("Research slug (for cache filename)", "genre_research")
    else:
        ids_input = st.text_area("App IDs (one per line or comma-separated)", "")
        slug_input = st.text_input("Research slug (for cache filename)", "manual_research")

    min_tag_reviews = st.number_input("Min reviews (pre-filter)", 0, 100000, 100, step=50)

    st.divider()
    st.header("Revenue Coefficients")
    reviews_multiplier = st.number_input("Reviews multiplier", 1, 200, DEFAULT_REVIEWS_MULTIPLIER, step=1)
    sales_coeff = st.number_input("Sales coefficient", 0.1, 5.0, DEFAULT_SALES_COEFF, step=0.1)
    regional_coeff = st.number_input("Regional coefficient", 0.1, 3.0, DEFAULT_REGIONAL_COEFF, step=0.05)
    steam_cut = st.slider("Steam cut %", 0, 50, int(DEFAULT_STEAM_CUT * 100)) / 100
    taxes = st.slider("Taxes %", 0, 50, int(DEFAULT_TAXES * 100)) / 100
    wishlist_coeff = st.number_input("Wishlist / follower ratio", 1, 50, DEFAULT_WISHLIST_COEFF)

    st.divider()
    fetch_btn = st.button("Fetch Data", type="primary")


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _parse_manual_ids(raw: str) -> list[int]:
    parts = raw.replace("\n", ",").split(",")
    ids = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            ids.append(int(p))
    return ids


if fetch_btn:
    if mode == "Tag Discovery":
        tags = [t.strip() for t in tags_input.split(",") if t.strip()]
        if not tags:
            st.error("Enter at least one tag.")
            st.stop()

        with st.spinner("Discovering apps by tag…"):
            discovered = discover_apps(tags, logic=logic, max_results=int(max_results))

        if not discovered:
            st.warning("No apps found for those tags.")
            st.stop()

        appids = list(discovered.keys())
        st.info(f"Found {len(appids)} apps. Fetching details…")
    else:
        discovered = {}
        appids = _parse_manual_ids(ids_input)
        if not appids:
            st.error("Enter at least one valid App ID.")
            st.stop()

    progress_bar = st.progress(0, text="Fetching app details…")

    def _progress(current: int, total: int, name: str):
        pct = current / total
        progress_bar.progress(pct, text=f"[{current}/{total}] {name}")

    records = enrich_apps(
        appids,
        names=discovered,
        progress_callback=_progress,
        min_reviews=int(min_tag_reviews),
    )
    progress_bar.empty()

    if not records:
        st.error("No records returned.")
        st.stop()

    slug = slug_input.strip().replace(" ", "_") or "research"
    cache_path = save_cache(records, slug)
    st.success(f"Fetched {len(records)} games. Saved to `{cache_path}`.")

    st.session_state["records"] = records
    st.session_state["active_run"] = cache_path
    st.query_params["run"] = cache_path
    st.rerun()


# ── Main Dashboard ────────────────────────────────────────────────────────────

if "records" not in st.session_state:
    st.info("Use the sidebar to fetch data or load a previous run.")
    st.stop()

active_run = st.session_state.get("active_run")
def _is_local() -> bool:
    host = st.context.headers.get("host", "")
    return host.startswith("localhost") or host.startswith("127.0.0.1")

if active_run:
    col_title, col_del = st.columns([8, 1])
    col_title.header(_run_label(active_run))
    if _is_local() and col_del.button("🗑️", help="Delete this run", key="delete_run"):
        if os.path.exists(active_run):
            os.remove(active_run)
        del st.session_state["records"]
        del st.session_state["active_run"]
        st.query_params.clear()
        st.rerun()

raw_records = st.session_state["records"]

enriched = enrich_records(
    raw_records,
    wishlist_coeff=int(wishlist_coeff),
    reviews_multiplier=int(reviews_multiplier),
    sales_coeff=sales_coeff,
    regional_coeff=regional_coeff,
    steam_cut=steam_cut,
    taxes=taxes,
)

df = to_dataframe(enriched)

tab1, tab2, tab3 = st.tabs(["Summary", "Games Table", "Charts"])


# ── Tab 1: Summary ────────────────────────────────────────────────────────────

with tab1:
    rev_q = compute_quartiles(enriched, "revenue_estimate")
    review_q = compute_quartiles(enriched, "total_reviews")
    price_q = compute_quartiles(enriched, "price_usd")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Games", len(enriched))
    c2.metric("Median Revenue", f"${rev_q['median']:,.0f}")
    c3.metric("Q1 Revenue", f"${rev_q['Q1']:,.0f}")
    c4.metric("Q3 Revenue", f"${rev_q['Q3']:,.0f}")

    st.subheader("Quartile Table")
    quartile_rows = []
    for label, q in [("Revenue ($)", rev_q), ("Total Reviews", review_q), ("Price ($)", price_q)]:
        quartile_rows.append({
            "Metric": label,
            "Min": f"{q['min']:,.0f}",
            "Q1": f"{q['Q1']:,.0f}",
            "Median": f"{q['median']:,.0f}",
            "Q3": f"{q['Q3']:,.0f}",
            "Max": f"{q['max']:,.0f}",
            "Mean": f"{q['mean']:,.0f}",
        })
    st.dataframe(pd.DataFrame(quartile_rows).set_index("Metric"), use_container_width=True)


# ── Tab 2: Games Table ────────────────────────────────────────────────────────

with tab2:
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        max_price = max((r.get("price_usd", 0) or 0 for r in enriched), default=100)
        price_range = st.slider("Price range ($)", 0.0, max(max_price, 100.0), (0.0, max(max_price, 100.0)))
    with fc2:
        min_reviews = st.number_input("Min total reviews", 0, 100000, 0, step=10)
    with fc3:
        exclude_ea = st.checkbox("Exclude Early Access")

    filtered = [
        r for r in enriched
        if price_range[0] <= (r.get("price_usd") or 0) <= price_range[1]
        and (r.get("total_reviews") or 0) >= min_reviews
        and not (exclude_ea and r.get("is_early_access"))
    ]

    st.caption(f"Showing {len(filtered)} of {len(enriched)} games")

    display_cols = [
        "name", "store_url", "total_reviews", "reviews_30d", "reviews_1y", "reviews_3y",
        "review_score", "price_usd",
        "revenue_total", "revenue_30d", "revenue_1y", "revenue_3y",
        "wishlist_estimate", "followers", "is_early_access", "release_date", "tags",
    ]
    fdf = to_dataframe(filtered)
    fdf["store_url"] = fdf.index.map(lambda a: f"https://store.steampowered.com/app/{a}/")
    cols_present = [c for c in display_cols if c in fdf.columns]

    st.dataframe(
        fdf[cols_present],
        column_config={
            "name": st.column_config.TextColumn("Name"),
            "store_url": st.column_config.LinkColumn("Steam Page", display_text="Open"),
            "total_reviews": st.column_config.NumberColumn("Reviews (total)"),
            "reviews_30d": st.column_config.NumberColumn("Reviews (30d)"),
            "reviews_1y": st.column_config.NumberColumn("Reviews (1yr)"),
            "reviews_3y": st.column_config.NumberColumn("Reviews (3yr)"),
            "review_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.2f"),
            "price_usd": st.column_config.NumberColumn("Price $", format="$%.2f"),
            "revenue_total": st.column_config.NumberColumn("Revenue (total)", format="$%d"),
            "revenue_30d": st.column_config.NumberColumn("Revenue (30d)", format="$%d"),
            "revenue_1y": st.column_config.NumberColumn("Revenue (1yr)", format="$%d"),
            "revenue_3y": st.column_config.NumberColumn("Revenue (3yr)", format="$%d"),
            "wishlist_estimate": st.column_config.NumberColumn("Wishlists Est."),
            "followers": st.column_config.NumberColumn("Followers"),
            "is_early_access": st.column_config.CheckboxColumn("EA"),
            "release_date": st.column_config.DateColumn("Released"),
        },
        use_container_width=True,
        height=500,
    )

    if filtered:
        buf = io.BytesIO()
        fdf[cols_present].to_excel(buf, index=True, engine="openpyxl")
        st.download_button(
            "Export to XLSX",
            data=buf.getvalue(),
            file_name="steam_research.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ── Tab 3: Charts ─────────────────────────────────────────────────────────────

with tab3:
    if not enriched:
        st.info("No data to chart.")
    else:
        top_n = st.slider("Top N games", 5, 50, 20)
        chart_df = df.reset_index().copy()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Reviews (30d)")
            r30 = chart_df[chart_df["reviews_30d"].notna()].nlargest(top_n, "reviews_30d")
            if not r30.empty:
                fig1 = px.bar(r30, x="reviews_30d", y="name", orientation="h",
                              labels={"reviews_30d": "Reviews (30d)", "name": ""},
                              color="is_early_access",
                              color_discrete_map={True: "#f0a500", False: "#1a9de0"})
                fig1.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("No 30d review data available.")

        with col2:
            st.subheader("Revenue (30d)")
            rev30 = chart_df[chart_df["revenue_30d"].notna()].nlargest(top_n, "revenue_30d")
            if not rev30.empty:
                fig2 = px.bar(rev30, x="revenue_30d", y="name", orientation="h",
                              labels={"revenue_30d": "Revenue 30d ($)", "name": ""},
                              color="is_early_access",
                              color_discrete_map={True: "#f0a500", False: "#1a9de0"})
                fig2.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No 30d revenue data available.")

        st.subheader("Wishlists vs Revenue (30d)")
        scatter_df = chart_df[
            chart_df["wishlist_estimate"].notna() &
            chart_df["revenue_30d"].notna() &
            (chart_df["wishlist_estimate"] > 0)
        ].copy()
        if not scatter_df.empty:
            scatter_df["ea_label"] = scatter_df["is_early_access"].map(
                {True: "Early Access", False: "Full Release"}
            )
            fig3 = px.scatter(
                scatter_df,
                x="wishlist_estimate",
                y="revenue_30d",
                hover_data=["name"],
                color="ea_label",
                labels={"wishlist_estimate": "Wishlists Est.", "revenue_30d": "Revenue 30d ($)", "ea_label": ""},
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Not enough data for scatter.")
