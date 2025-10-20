import streamlit as st
import feedparser
from datetime import datetime, timedelta
from dateutil import parser as dtparser
import pandas as pd
import re
from collections import defaultdict
from pathlib import Path
import os

# =========================
# Page & Style
# =========================
st.set_page_config(
    page_title="News Agent",
    page_icon="🗞️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Simple CSS polish (optional) ----
st.markdown("""
<style>
/* nicer card feel for result containers */
.block-container {padding-top: 1.4rem;}
.match-reason {opacity: 0.7; font-size: 0.85rem;}
.smallnote {opacity: 0.8;}
.logo-row {display:flex; align-items:center; gap:18px;}
.logo-row img {height:54px;}
.app-title {font-size: 2rem; font-weight: 700; margin: 0;}
.app-tag {margin-top:-6px; opacity: 0.8;}
</style>
""", unsafe_allow_html=True)

# ---- Header with logo (robust path + helpful debug) ----
with st.container():
    col_logo, col_title = st.columns([1, 8])
    with col_logo:
        try:
            # Build a path relative to this file (works the same locally and on Streamlit Cloud)
            logo_path = Path(__file__).parent / "assets" / "news_agent_logo.png"
            if logo_path.exists():
                st.image(str(logo_path))
            else:
                st.caption("Logo not found at: " + str(logo_path))
                # Debug hints to help you verify paths
                st.caption("CWD: " + os.getcwd())
                st.caption("Assets folder present? " + str((Path(__file__).parent / 'assets').exists()))
        except Exception as e:
            st.caption(f"Logo load error: {e}")
    with col_title:
        st.markdown('<div class="app-title">🗞️ News Agent</div>', unsafe_allow_html=True)
        st.markdown('<div class="app-tag">Curate • Filter • Search</div>', unsafe_allow_html=True)


# =========================
# Feeds by Category
# =========================
FEEDS = {
    "Top/General": [
        "https://feeds.reuters.com/reuters/topNews",
        "https://apnews.com/hub/ap-top-news?output=rss",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ],
    "Business": [
        "https://feeds.reuters.com/reuters/businessNews",
    ],
    "Technology": [
        "https://apnews.com/hub/technology?output=rss",
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
    ],
    "EV & Energy": [
        "https://electrek.co/feed/",
    ],
}

ALL_FEEDS_FLAT = [u for lst in FEEDS.values() for u in lst]

# =========================
# Helpers: text matching
# =========================
def normalize(text: str) -> str:
    return (text or "").strip()

def is_quoted(term: str) -> bool:
    t = term.strip()
    return len(t) >= 2 and t[0] == '"' and t[-1] == '"'

def strip_quotes(term: str) -> str:
    return term.strip()[1:-1] if is_quoted(term) else term.strip()

def loose_match(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()

def exact_word_match(haystack: str, phrase: str) -> bool:
    pattern = r"\b" + re.escape(phrase) + r"\b"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None

def match_term(text: str, term: str) -> bool:
    if not term:
        return False
    text = text or ""
    if is_quoted(term):
        return exact_word_match(text, strip_quotes(term))
    else:
        return loose_match(text, term)

def children_match(text: str, children: list[str], mode: str) -> tuple[bool, str]:
    """
    Returns (ok?, reason). mode in {"ANY","ALL"}.
    If no children provided, treat as ok (no child filter).
    """
    kids = [c for c in children if c.strip()]
    if not kids:
        return True, "no child terms provided"
    hits = [c for c in kids if match_term(text, c)]
    if mode == "ALL":
        ok = len(hits) == len(kids)
        reason = f"children {' & '.join(kids)} {'all matched' if ok else 'not all matched'}"
    else:
        ok = len(hits) > 0
        reason = f"child matched: {hits[0]}" if ok else "no child matched"
    return ok, reason

# =========================
# Helpers: dates & fetching
# =========================
def safe_parse_date(entry) -> datetime | None:
    # Common textual date fields
    for key in ("published", "updated", "created"):
        val = getattr(entry, key, None)
        if not val and isinstance(entry, dict):
            val = entry.get(key)
        try:
            if val:
                return dtparser.parse(val)
        except Exception:
            pass
    # struct_time fields
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if not val and isinstance(entry, dict):
            val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                pass
    return None

@st.cache_data(show_spinner=False, ttl=600)
def fetch_entries(feeds: list[str], since_days: int) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=since_days)
    results = []
    for url in feeds:
        try:
            rss = feedparser.parse(url)
        except Exception:
            continue
        source_name = normalize(getattr(rss.feed, "title", url))
        for e in rss.entries:
            dt = safe_parse_date(e)
            if dt and dt < cutoff:
                continue
            title = normalize(getattr(e, "title", ""))
            summary = normalize(getattr(e, "summary", ""))
            link = normalize(getattr(e, "link", ""))
            results.append(
                {
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": dt,
                    "source": source_name,
                    "feed_url": url,
                }
            )
    results.sort(key=lambda x: x["published"] or datetime.min, reverse=True)
    return results

def to_dataframe(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items)
    if "published" in df.columns:
        df["published"] = df["published"].astype(str)
    return df

# =========================
# Sidebar (filters & tips)
# =========================
with st.sidebar:
    st.header("Filters")
    parent = st.text_input("Parent term (required)", value="Tesla")

    st.caption("Child terms refine results. You can enter quoted exact phrases or loose terms.")
    c1 = st.text_input('Child #1 (e.g. "FSD")', value="")
    c2 = st.text_input("Child #2", value="")
    c3 = st.text_input("Child #3", value="")
    c4 = st.text_input("Child #4", value="")
    c5 = st.text_input("Child #5", value="")
    children = [c1, c2, c3, c4, c5]

    mode = st.radio("Children must match…", ["ANY", "ALL"], horizontal=True)

    col_days, col_limit = st.columns(2)
    with col_days:
        since_days = st.number_input("Look back (days)", min_value=1, max_value=365, value=30, step=1)
    with col_limit:
        limit = st.number_input("Max results", min_value=1, max_value=50, value=20, step=1)

    st.divider()
    st.subheader("Categories")
    # Choose categories to include
    selected_cats = []
    for cat in FEEDS.keys():
        if st.checkbox(cat, value=True):
            selected_cats.append(cat)

    st.divider()
    st.subheader("How to match exact words")
    st.info(
        'Use **quotes** for exact phrases.\n\n'
        '- **Exact:** `"full self-driving"` matches only those exact words together.\n'
        '- **Loose:** `FSD` (no quotes) matches anything containing FSD (case-insensitive).',
        icon="🔎",
    )

    run_search = st.button("Run search", type="primary")

# =========================
# Search & Results
# =========================
if run_search:
    if not parent.strip():
        st.warning("Please enter a Parent term.")
        st.stop()

    feeds_to_use = [u for cat in selected_cats for u in FEEDS.get(cat, [])]
    if not feeds_to_use:
        feeds_to_use = ALL_FEEDS_FLAT  # fallback if nothing selected

    with st.spinner("Fetching articles…"):
        entries = fetch_entries(feeds_to_use, since_days)

    matched = []
    for item in entries:
        haystack = " ".join([
            item["title"] or "",
            item["summary"] or "",
            item["source"] or "",
        ])
        # Must match parent
        if not match_term(haystack, parent):
            continue
        # Children rule
        ok_child, child_reason = children_match(haystack, children, mode)
        if not ok_child:
            continue

        reason_bits = [f'parent matched: {parent}']
        if child_reason:
            reason_bits.append(child_reason)
        reason = " | ".join(reason_bits)

        matched.append({**item, "reason": reason})
        if len(matched) >= int(limit):
            break

    st.subheader(f"Results ({len(matched)})")

    if not matched:
        st.info(
            "No articles matched. Tips:\n"
            "• Remove quotes for broader matching\n"
            "• Increase the look-back window\n"
            "• Deselect some categories to reduce noise\n"
            "• Try a simpler Parent term",
            icon="💡",
        )
        st.stop()

    # ---- Group into tabs by source ----
    by_source = defaultdict(list)
    for row in matched:
        by_source[row["source"]].append(row)

    tab_titles = [f"{src} ({len(rows)})" for src, rows in by_source.items()]
    tabs = st.tabs(tab_titles)

    for (src, rows), tab in zip(by_source.items(), tabs):
        with tab:
            for row in rows:
                with st.container(border=True):
                    st.markdown(f"### [{row['title']}]({row['link']})")
                    meta = []
                    if row["source"]:
                        meta.append(f"**Source:** {row['source']}")
                    if row["published"]:
                        meta.append(f"**Published:** {row['published'].strftime('%Y-%m-%d %H:%M')} UTC")
                    if meta:
                        st.write("  •  ".join(meta))
                    if row["summary"]:
                        st.write(row["summary"])
                    st.markdown(f'<div class="match-reason">Match details: {row["reason"]}</div>', unsafe_allow_html=True)

    # ---- Downloads (CSV & JSONL) ----
    df = to_dataframe(matched)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    jsonl_str = "\n".join(df.to_dict(orient="records").__repr__().strip("[]").split("}, {")).replace("}, {", "}\n{")
    # Safer JSONL:
    import json
    jsonl_str = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in df.to_dict(orient="records"))

    st.download_button("Download CSV", data=csv_bytes, file_name="news_agent_results.csv", mime="text/csv")
    st.download_button("Download JSONL", data=jsonl_str.encode("utf-8"), file_name="news_agent_results.jsonl", mime="application/json")

    # ---- Lightweight "summary" (no API key required) ----
    # We'll produce a compact bullet list of titles by source as a quick digest.
    with st.expander("Quick digest (titles by source)"):
        for src, rows in by_source.items():
            st.markdown(f"**{src}**")
            for row in rows[:5]:
                st.write(f"- {row['title']}")

else:
    st.caption("Ready when you are — set filters in the sidebar and hit **Run search**.")
