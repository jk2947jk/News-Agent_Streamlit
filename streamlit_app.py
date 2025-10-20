import streamlit as st
import pandas as pd
from app2 import run_search, DEFAULT_FEEDS  # reuse logic from CLI

st.set_page_config(page_title="News Agent", page_icon="📰", layout="wide")

st.title("📰 News Agent — Search Feeds")

with st.sidebar:
    st.header("Filters")
    query = st.text_input("Parent query (fuzzy contains)", value="AI")

    col_a, col_b = st.columns(2)
    with col_a:
        since_unit = st.selectbox("Window unit", options=["days (d)", "hours (h)"], index=0)
    with col_b:
        since_qty = st.number_input("Window size", min_value=1, max_value=90, value=7, step=1)

    unit_char = "d" if since_unit.startswith("days") else "h"
    since = f"{int(since_qty)}{unit_char}"

    limit = st.slider("Limit (1–50; step 5)", min_value=1, max_value=50, value=20, step=5)

    st.markdown("**Keywords (optional)** — up to 5. Put quotes for an exact phrase; no quotes for fuzzy word match.")
    kw1 = st.text_input('Keyword 1', value="")
    kw2 = st.text_input('Keyword 2', value="")
    kw3 = st.text_input('Keyword 3', value="")
    kw4 = st.text_input('Keyword 4', value="")
    kw5 = st.text_input('Keyword 5', value="")
    keywords = [k for k in [kw1, kw2, kw3, kw4, kw5] if k.strip()]

    st.markdown("---")
    with st.expander("Feeds (advanced)"):
        feeds_text = st.text_area(
            "One feed URL per line",
            value="\n".join(DEFAULT_FEEDS),
            height=150,
        )
        feeds = [line.strip() for line in feeds_text.splitlines() if line.strip()]

    run_btn = st.button("🔍 Run Search", type="primary")

@st.cache_data(ttl=180, show_spinner=False)
def cached_search(query: str, since: str, limit: int, keywords: tuple, feeds: tuple) -> pd.DataFrame:
    # cache requires hashable types (hence tuples)
    return run_search(query=query, since=since, limit=limit, keywords=list(keywords), feeds=list(feeds))

if run_btn:
    try:
        df = cached_search(query, since, limit, tuple(keywords), tuple(feeds))
    except Exception as e:
        st.error(f"Search failed: {e}")
        st.stop()

    if df.empty:
        st.warning("No results matched your filters.")
    else:
        st.success(f"Found {len(df)} results")

        # Nice, link-friendly view
        with st.container():
            for i, row in df.iterrows():
                with st.container(border=True):
                    st.markdown(f"### {row['Title']}")
                    meta_cols = st.columns([1, 1, 2])
                    meta_cols[0].markdown(f"**Source:** {row['Source']}")
                    meta_cols[1].markdown(f"**Published:** {row['Published']}")
                    meta_cols[2].markdown(f"[Open link]({row['Link']})")

                    if row.get("Summary"):
                        with st.expander("Summary"):
                            st.write(row["Summary"])

        # Also show a table for quick scanning
        st.divider()
        st.markdown("#### Table view")
        display_df = df.drop(columns=["Summary"])
        st.dataframe(display_df, use_container_width=True)
else:
    st.info("Set your filters in the sidebar, then click **Run Search**.")
