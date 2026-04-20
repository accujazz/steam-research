import io
import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from calculator import (
    DEFAULT_REGIONAL_COEFF,
    DEFAULT_SALES_COEFF,
    DEFAULT_STEAM_CUT,
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
st.title("Steam Genre Research")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Data Source")
    mode = st.radio("Input mode", ["Tag Discovery", "Manual App IDs"])

    if mode == "Tag Discovery":
        tags_input = st.text_input("Tags (comma-separated)", "Roguelite")
        logic = st.radio("Tag logic", ["OR", "AND"])
        slug_input = st.text_input("Research slug (for cache filename)", "genre_research")
    else:
        ids_input = st.text_area("App IDs (one per line or comma-separated)", "")
        slug_input = st.text_input("Research slug (for cache filename)", "manual_research")

    st.divider()
    st.header("Revenue Coefficients")
    sales_coeff = st.number_input("Sales coefficient", 0.1, 5.0, DEFAULT_SALES_COEFF, step=0.1)
    regional_coeff = st.number_input("Regional coefficient", 0.1, 3.0, DEFAULT_REGIONAL_COEFF, step=0.05)
    steam_cut = st.slider("Steam cut %", 0, 40, int(DEFAULT_STEAM_CUT * 100)) / 100
    wishlist_coeff = st.number_input("Wishlist / follower ratio", 1, 50, DEFAULT_WISHLIST_COEFF)

    st.divider()
    st.header("Cache")
    cache_files = list_cache_files()
    cache_options = ["(none)"] + cache_files
    selected_cache = st.selectbox("Load existing run", cache_options)
    load_btn = st.button("Load from cache")

    st.divider()
    fetch_btn = st.button("Fetch Data", type="primary")


# ── Fetch / Load ─────────────────────────────────────────────────────────────

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
            discovered = discover_apps(tags, logic=logic)

        if not discovered:
            st.warning("No apps found for those tags.")
            st.stop()

        appids = list(discovered.keys())
        st.info(f"Found {len(appids)} apps. Fetching details…")
    else:
        appids = _parse_manual_ids(ids_input)
        if not appids:
            st.error("Enter at least one valid App ID.")
            st.stop()

    progress_bar = st.progress(0, text="Fetching app details…")

    def _progress(current: int, total: int, name: str):
        pct = current / total
        progress_bar.progress(pct, text=f"[{current}/{total}] {name}")

    records = enrich_apps(appids, progress_callback=_progress)
    progress_bar.empty()

    if not records:
        st.error("No records returned.")
        st.stop()

    slug = slug_input.strip().replace(" ", "_") or "research"
    cache_path = save_cache(records, slug)
    st.success(f"Fetched {len(records)} games. Saved to `{cache_path}`.")

    st.session_state["records"] = records

elif load_btn and selected_cache != "(none)":
    try:
        records = load_cache(selected_cache)
        st.session_state["records"] = records
        st.success(f"Loaded {len(records)} games from `{selected_cache}`.")
    except Exception as e:
        st.error(f"Failed to load cache: {e}")


# ── Main Dashboard ────────────────────────────────────────────────────────────

if "records" not in st.session_state:
    st.info("Use the sidebar to fetch data or load a cached run.")
    st.stop()

raw_records = st.session_state["records"]

enriched = enrich_records(
    raw_records,
    wishlist_coeff=int(wishlist_coeff),
    sales_coeff=sales_coeff,
    regional_coeff=regional_coeff,
    steam_cut=steam_cut,
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
        "name", "total_reviews", "reviews_30d", "reviews_1y", "reviews_3y",
        "review_score", "price_usd", "revenue_estimate", "wishlist_estimate",
        "followers", "is_early_access", "release_date", "tags",
    ]
    fdf = to_dataframe(filtered)
    cols_present = [c for c in display_cols if c in fdf.columns]

    st.dataframe(
        fdf[cols_present],
        column_config={
            "name": st.column_config.TextColumn("Name"),
            "total_reviews": st.column_config.NumberColumn("Reviews (total)"),
            "reviews_30d": st.column_config.NumberColumn("Reviews (30d)"),
            "reviews_1y": st.column_config.NumberColumn("Reviews (1yr)"),
            "reviews_3y": st.column_config.NumberColumn("Reviews (3yr)"),
            "review_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.2f"),
            "price_usd": st.column_config.NumberColumn("Price $", format="$%.2f"),
            "revenue_estimate": st.column_config.NumberColumn("Revenue Est.", format="$%d"),
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
        rev_q = compute_quartiles(enriched, "revenue_estimate")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Revenue Distribution")
            plot_df = df[df["revenue_estimate"] > 0].copy() if "revenue_estimate" in df.columns else pd.DataFrame()
            if not plot_df.empty:
                fig = px.histogram(
                    plot_df,
                    x="revenue_estimate",
                    nbins=40,
                    log_x=True,
                    labels={"revenue_estimate": "Revenue Estimate ($)"},
                )
                for key, color in [("Q1", "orange"), ("median", "red"), ("Q3", "green")]:
                    fig.add_vline(x=rev_q[key], line_dash="dash", line_color=color,
                                  annotation_text=key, annotation_position="top")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No paid games to chart.")

        with col2:
            st.subheader("Price vs. Reviews")
            if "price_usd" in df.columns and "total_reviews" in df.columns:
                scatter_df = df[(df["price_usd"] > 0) & (df["total_reviews"] > 0)].copy()
                scatter_df["ea_label"] = scatter_df["is_early_access"].map(
                    {True: "Early Access", False: "Full Release"}
                )
                if not scatter_df.empty:
                    fig2 = px.scatter(
                        scatter_df.reset_index(),
                        x="price_usd",
                        y="total_reviews",
                        size="revenue_estimate",
                        color="ea_label",
                        hover_data=["name"],
                        labels={
                            "price_usd": "Price ($)",
                            "total_reviews": "Total Reviews",
                            "ea_label": "",
                        },
                        size_max=40,
                    )
                    st.plotly_chart(fig2, use_container_width=True)

