#!/usr/bin/env python
"""
News search CLI + library

- Default limit = 20 (range 1–50, step 5).
- Supports up to 5 optional "keywords":
    * With quotes => exact phrase match
    * Without quotes => fuzzy word match (anywhere in text)
- Exposes a pure function `run_search()` used by Streamlit.

Usage examples:
  python app2.py search --query "AI" --since 7d --limit 20
  python app2.py search --query "election" --kw "United States" --kw chips --limit 35
"""

from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Iterable, Tuple
import re

import feedparser
import pandas as pd
import typer
from rich.console import Console
from rich.table import Table
from dateutil import tz, parser as dateparser

app = typer.Typer(add_completion=False)
console = Console()

# ---- Configuration ----
DEFAULT_FEEDS = [
    # Feel free to edit/extend this list. These are commonly reliable RSS feeds.
    "https://feeds.reuters.com/reuters/topNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://www.theguardian.com/world/rss",
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
]

Result = Dict[str, Any]


def _normalize_time(entry: Dict[str, Any]) -> datetime | None:
    """
    Try to extract a timezone-aware datetime from an RSS entry.
    """
    # Prefer structured times
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        if entry.get(key):
            try:
                return datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
            except Exception:
                pass
    # Fallback: parse strings if available
    for key in ("published", "updated", "created"):
        if entry.get(key):
            try:
                dt = dateparser.parse(entry[key])
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return None


def _text_haystack(entry: Dict[str, Any]) -> str:
    parts = [
        entry.get("title", ""),
        entry.get("summary", ""),
        entry.get("description", ""),
    ]
    return " ".join(p for p in parts if p).lower()


def _parse_keywords(raw_keywords: Iterable[str]) -> Tuple[List[str], List[str]]:
    """
    Return (phrases, words)
    - phrases: quoted strings => exact phrase match (case-insensitive)
    - words: unquoted tokens => fuzzy contains
    """
    phrases: List[str] = []
    words: List[str] = []
    for kw in raw_keywords:
        kw = kw.strip()
        # If user passed quoted keyword in CLI (typer already strips quotes sometimes),
        # accept it as a phrase if it contains spaces OR was clearly quoted.
        if (len(kw) >= 2 and kw[0] == '"' and kw[-1] == '"') or (" " in kw):
            phrases.append(kw.strip('"').lower())
        else:
            words.append(kw.lower())
    return phrases, words


def _matches(haystack: str, phrases: List[str], words: List[str]) -> bool:
    # Must satisfy ALL phrases and ALL words (AND logic)
    for ph in phrases:
        if ph not in haystack:
            return False
    for w in words:
        if w not in haystack:
            return False
    return True


def _fetch_entries(feeds: Iterable[str]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for url in feeds:
        parsed = feedparser.parse(url)
        if parsed.bozo and getattr(parsed, "bozo_exception", None):
            # Keep calm and skip bozo feeds; Streamlit UI will still work with others.
            continue
        source_title = parsed.feed.get("title", url) if parsed.get("feed") else url
        for e in parsed.get("entries", []):
            dt = _normalize_time(e)
            entries.append(
                {
                    "title": e.get("title", "").strip(),
                    "link": e.get("link", "").strip(),
                    "summary": e.get("summary", "") or e.get("description", ""),
                    "published": dt,
                    "source": source_title,
                }
            )
    return entries


def run_search(
    query: str,
    since: str = "7d",
    limit: int = 20,
    keywords: Iterable[str] = (),
    feeds: Iterable[str] = DEFAULT_FEEDS,
) -> pd.DataFrame:
    """
    Core search function used by both CLI and Streamlit.

    Args:
        query: Parent query string (fuzzy contains).
        since: 'Nd' (days) or 'Nh' (hours). Example: '7d', '24h'.
        limit: 1..50 (results after filtering, sorted by recency).
        keywords: Up to 5 additional keyword strings (quoted => exact phrase).
        feeds: Iterable of feed URLs.

    Returns:
        pandas.DataFrame with columns: ['Title','Source','Published','Link','Summary']
    """
    # Parse since
    now = datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)([dh])", since.strip().lower())
    if not m:
        raise ValueError("since must look like '7d' or '24h'")
    qty, unit = int(m.group(1)), m.group(2)
    delta = timedelta(days=qty) if unit == "d" else timedelta(hours=qty)
    cutoff = now - delta

    # Fetch
    all_entries = _fetch_entries(feeds)

    # Build text filters
    parent = query.strip().lower()
    phrases, words = _parse_keywords(keywords)

    # Filter
    filtered: List[Result] = []
    for e in all_entries:
        # time filter
        if e["published"] is None or e["published"] < cutoff:
            continue

        hay = _text_haystack(e)
        if parent and parent not in hay:
            continue
        if not _matches(hay, phrases, words):
            continue

        filtered.append(e)

    # Sort newest first
    filtered.sort(key=lambda x: (x["published"] or datetime.fromtimestamp(0, tz=timezone.utc)), reverse=True)

    # Enforce limit
    limit = max(1, min(50, limit))
    filtered = filtered[:limit]

    # DataFrame
    df = pd.DataFrame(
        [
            {
                "Title": r["title"],
                "Source": r["source"],
                "Published": r["published"].astimezone(tz.tzlocal()).strftime("%Y-%m-%d %H:%M"),
                "Link": r["link"],
                "Summary": r["summary"],
            }
            for r in filtered
        ]
    )
    return df


# ---------------- CLI ----------------

@app.command()
def search(
    query: str = typer.Option(..., "--query", "-q", help="Parent search query (fuzzy contains)."),
    since: str = typer.Option("7d", "--since", help="Time window like '7d' or '24h'."),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results (1..50, step 5)."),
    kw: List[str] = typer.Option(None, "--kw", help='Up to 5 keywords. Use quotes for exact phrase, e.g. --kw "United States" --kw chips'),
):
    """
    Search news feeds and print a nice table.
    """
    # Enforce increments of 5 (but still accept any in range by snapping)
    if limit < 1 or limit > 50:
        limit = max(1, min(50, limit))
    if limit % 5 != 0 and limit not in (1, 2, 3, 4):  # allow tiny values for testing
        limit = ((limit + 4) // 5) * 5
        limit = min(limit, 50)

    kw = kw or []
    if len(kw) > 5:
        kw = kw[:5]

    try:
        df = run_search(query=query, since=since, limit=limit, keywords=kw)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if df.empty:
        console.print("[yellow]No results matched your filters.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Search results ({len(df)})")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Source", style="magenta")
    table.add_column("Published", justify="center")
    table.add_column("Link")

    for i, row in df.iterrows():
        table.add_row(
            str(i + 1),
            row["Title"],
            row["Source"],
            row["Published"],
            row["Link"],
        )

    console.print(table)


if __name__ == "__main__":
    app()
