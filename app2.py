#!/usr/bin/env python3
# ===========================================================
#  News Agent — app2.py  (v2)
#
#  HOW TO RUN (for beginners using VS Code)
#  ----------------------------------------
#  1.  Open VS Code.
#      Go to File → Open Folder → choose your "News Agent" project folder.
#
#  2.  Open the terminal (Ctrl + `)  ← that’s the key above Tab.
#      You should see something like:
#         PS C:\Users\<you>\Documents\News Agent>
#
#  3.  Activate your virtual environment (if using one):
#         .\.venv\Scripts\activate
#
#  4.  Install required packages (one time):
#         python -m pip install click feedparser rich
#
#  5.  Run your news search:
#         python app2.py search --presets tech --since 7d --limit 20
#
#      → Shows up to 20 recent tech headlines from the past 7 days.
#        If fewer than 20 exist, you’ll get only the available ones.
#
#  6.  Optional features:
#         --save-csv results.csv   → saves table as a spreadsheet file
#         --save-md results.md     → saves table as Markdown text
#         --open                   → lets you pick which results to open in your browser
#
#      Examples:
#         python app2.py search --presets tech --since 30d --limit 20 --save-csv results.csv
#         python app2.py search --presets ai --since 7d -k "AI" -k "=OpenAI" --open
#
#  7.  Check output files in the Explorer sidebar (left of VS Code).
#
# ===========================================================

import re
import sys
import time
import csv
import textwrap
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

try:
    import click
except ImportError:
    print("Missing dependency: click. Install with: pip install click", file=sys.stderr)
    sys.exit(1)

try:
    import feedparser
except ImportError:
    print("Missing dependency: feedparser. Install with: pip install feedparser", file=sys.stderr)
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Missing dependency: rich. Install with: pip install rich", file=sys.stderr)
    sys.exit(1)


# -----------------------------
# Preset RSS feeds
# -----------------------------
PRESETS = {
    "top": [
        "https://feeds.reuters.com/reuters/topNews",
        "https://www.apnews.com/apf-topnews?output=rss",
        "http://feeds.bbci.co.uk/news/rss.xml",
        "http://rss.cnn.com/rss/edition.rss",
    ],
    "world": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.npr.org/rss/rss.php?id=1004",
    ],
    "tech": [
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://www.wired.com/feed/rss",
        "https://www.theguardian.com/uk/technology/rss",
    ],
    "business": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.bloomberg.com/feed/podcast/etf-report.xml",
        "https://www.ft.com/?format=rss",
    ],
    "ai": [
        "https://feeds.feedburner.com/venturebeat/SZYF",
        "https://www.marktechpost.com/feed/",
        "https://syncedreview.com/feed/",
        "https://www.thedecoder.com/feed/",
    ],
}


# -----------------------------
# Utilities
# -----------------------------
def parse_datetime_string(s: str) -> Optional[datetime]:
    """Parse absolute date in YYYY-MM-DD or YYYY/MM/DD -> UTC midnight."""
    s = s.strip()
    fmts = ["%Y-%m-%d", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            dt_naive = datetime.strptime(s, fmt)
            return dt_naive.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)

def parse_since_until(s: str, now: datetime) -> Optional[datetime]:
    """Relative (e.g. '7d') or absolute (YYYY-MM-DD) → UTC datetime."""
    if not s:
        return None
    m = _DURATION_RE.match(s)
    if m:
        qty = int(m.group(1))
        unit = m.group(2).lower()
        delta = {
            "s": timedelta(seconds=qty),
            "m": timedelta(minutes=qty),
            "h": timedelta(hours=qty),
            "d": timedelta(days=qty),
            "w": timedelta(weeks=qty),
        }[unit]
        return now - delta
    return parse_datetime_string(s)


def safe_get_published(entry) -> Optional[datetime]:
    """Convert feed entry published/updated time to aware UTC datetime if present."""
    st = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not st:
        return None
    try:
        ts = time.mktime(st)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


def normalize_text(s: str) -> str:
    return (s or "").strip()


def parse_keywords(keywords: Tuple[str, ...]) -> Tuple[Optional[Dict], List[Dict]]:
    """First keyword = parent; next up to 5 = children; prefix '=' for exact."""
    if not keywords:
        return None, []
    def to_kwd(raw: str) -> Dict:
        raw = raw.strip()
        exact = raw.startswith("=")
        if exact:
            raw = raw[1:].strip()
        return {"text": raw, "exact": exact}
    parsed = [to_kwd(k) for k in keywords if k and k.strip()]
    parent = parsed[0] if parsed else None
    children = parsed[1:6]
    return parent, children


def text_matches_keyword(text: str, kwd: Dict) -> bool:
    """Case-insensitive substring check."""
    haystack = text.lower()
    needle = kwd["text"].lower()
    return bool(needle) and needle in haystack


def matches_parent_children(title: str, summary: str, parent: Optional[Dict], children: List[Dict]) -> bool:
    """Parent only → must match; Parent+Children → parent & ≥1 child."""
    blob = f"{title} {summary}".strip()
    if not parent:
        return True
    if not text_matches_keyword(blob, parent):
        return False
    if not children:
        return True
    return any(text_matches_keyword(blob, c) for c in children)


def validate_limit(_ctx, _param, value: int) -> int:
    allowed = {1} | set(range(5, 51, 5))
    if value not in allowed:
        raise click.BadParameter("--limit must be 1 or 5,10,15,...,50")
    return value


def dedupe_entries(entries: List[dict]) -> List[dict]:
    seen, unique = set(), []
    for e in entries:
        key = (e.get("title", "").strip(), e.get("link", "").strip())
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def truncate(s: str, maxlen: int) -> str:
    if not s:
        return ""
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def export_csv(entries: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "source", "published_utc", "link", "summary"])
        writer.writeheader()
        for e in entries:
            pub = e["published"]
            writer.writerow({
                "title": e["title"],
                "source": e["source"],
                "published_utc": pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if isinstance(pub, datetime) else "",
                "link": e["link"],
                "summary": e["summary"],
            })


def export_md(entries: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Search results\n",
        "| # | Title | Source | Published (UTC) |",
        "|---:|---|---|---|",
    ]
    for i, e in enumerate(entries, 1):
        title = e["title"].replace("|", "\\|")
        link = e["link"]
        src = (e["source"] or "").replace("|", "\\|")
        pub = e["published"]
        pub_str = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if isinstance(pub, datetime) else "—"
        title_md = f"[{title}]({link})" if link else title
        lines.append(f"| {i} | {title_md} | {src} | {pub_str} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_selection(selection: str, max_index: int) -> List[int]:
    """Parse '1,3-5' → [1,3,4,5]."""
    out = set()
    for token in selection.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            out.update(range(max(1, start), min(max_index, end) + 1))
        else:
            try:
                n = int(token)
            except ValueError:
                continue
            if 1 <= n <= max_index:
                out.add(n)
    return sorted(out)


# -----------------------------
# CLI
# -----------------------------
@click.group(help="News Agent — Search & Keywords v2")
def cli():
    pass


@cli.command("search", help="Search news feeds with presets, date filters, and keywords.")
@click.option("--presets", type=click.Choice(sorted(PRESETS.keys())), multiple=True, help="Preset feed groups.")
@click.option("--feeds", multiple=True, help="RSS feed URLs.")
@click.option("--since", help='Filter newer than this (e.g. "7d" or "2025-10-01").')
@click.option("--until", help='Filter older than this (e.g. "1d" or "2025-10-10").')
@click.option("--limit", default=20, show_default=True, callback=validate_limit, type=int, help="Number of results to show (1 or 5–50).")
@click.option("--keywords", "-k", multiple=True, help="Parent first, then up to 5 children. Prefix '=' for exact.")
@click.option("--save-csv", type=click.Path(dir_okay=False, writable=True, path_type=Path), help="Save results as CSV.")
@click.option("--save-md", type=click.Path(dir_okay=False, writable=True, path_type=Path), help="Save results as Markdown.")
@click.option("--open", "open_links", is_flag=True, help="After showing results, choose which links to open in browser.")
def cmd_search(presets, feeds, since, until, limit, keywords, save_csv, save_md, open_links):
    console = Console()

    # Build feed list
    feed_urls = []
    for p in presets:
        feed_urls.extend(PRESETS.get(p, []))
    feed_urls.extend(list(feeds or []))
    if not feed_urls:
        feed_urls = PRESETS["top"]

    now_utc = datetime.now(timezone.utc)
    dt_since = parse_since_until(since, now_utc) if since else None
    dt_until = parse_since_until(until, now_utc) if until else None
    if dt_since and dt_until and dt_since > dt_until:
        console.print("[red]Error:[/red] --since is after --until.")
        sys.exit(2)

    parent_kwd, child_kwds = parse_keywords(keywords)
    all_entries, failures = [], []

    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            if getattr(parsed, "bozo", False) and getattr(parsed, "bozo_exception", None):
                failures.append((url, f"Parse issue: {parsed.bozo_exception}"))
            feed_title = (parsed.feed.get("title") if getattr(parsed, "feed", None) else None) or url

            for entry in parsed.entries:
                title = normalize_text(getattr(entry, "title", ""))
                link = normalize_text(getattr(entry, "link", ""))
                summary = normalize_text(getattr(entry, "summary", ""))
                published = safe_get_published(entry)

                if dt_since and published and published < dt_since:
                    continue
                if dt_until and published and published > dt_until:
                    continue
                if parent_kwd or child_kwds:
                    if not matches_parent_children(title, summary, parent_kwd, child_kwds):
                        continue

                all_entries.append({
                    "title": title or "(no title)",
                    "link": link,
                    "summary": summary,
                    "published": published,
                    "source": feed_title,
                })
        except Exception as e:
            failures.append((url, str(e)))

    all_entries = dedupe_entries(all_entries)

    def sort_key(e): return (0, -e["published"].timestamp()) if isinstance(e["published"], datetime) else (1, 0)
    all_entries.sort(key=sort_key)
    display_entries = all_entries[:limit]

    if failures:
        console.print("\n[yellow]Warnings:[/yellow]")
        for url, msg in failures:
            console.print(f"  • Failed to parse {url}\n    Reason: {msg}")

    if not display_entries:
        console.print("[bold]No results matched your filters.[/bold]")
        return

    table = Table(title="Search results", box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("#", justify="right", width=3)
    table.add_column("Title", width=48)
    table.add_column("Source", width=18)
    table.add_column("Published", width=22)
    table.add_column("Link", width=48)

    for i, e in enumerate(display_entries, 1):
        pub = e["published"]
        pub_str = pub.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if isinstance(pub, datetime) else "—"
        table.add_row(str(i), truncate(e["title"], 48), truncate(e["source"], 18), pub_str, truncate(e["link"], 48))
    console.print()
    console.print(table)
    console.print()

    if save_csv:
        try:
            export_csv(display_entries, save_csv)
            console.print(f"[green]Saved CSV:[/green] {save_csv}")
        except Exception as e:
            console.print(f"[red]Failed to save CSV:[/red] {e}")

    if save_md:
        try:
            export_md(display_entries, save_md)
            console.print(f"[green]Saved Markdown:[/green] {save_md}")
        except Exception as e:
            console.print(f"[red]Failed to save Markdown:[/red] {e}")

    if open_links:
        try:
            console.print("Enter result numbers to open (e.g. 1,3-5) or press Enter to skip.")
            selection = input("> ").strip()
            if selection:
                idxs = parse_selection(selection, len(display_entries))
                if not idxs:
                    console.print("[yellow]No valid selections.[/yellow]")
                else:
                    for i in idxs:
                        link = display_entries[i - 1]["link"]
                        if link:
                            webbrowser.open(link, new=2)
                            time.sleep(0.2)
            else:
                console.print("Skipped opening links.")
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")


# -----------------------------
# Entry point
# -----------------------------
if __name__ == "__main__":
    cli()
