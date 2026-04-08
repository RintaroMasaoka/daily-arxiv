#!/usr/bin/env python3
"""Fetch recent arXiv papers from cond-mat.str-el and cond-mat.stat-mech.

Queries the arXiv API (export.arxiv.org) and writes results to data/latest.json.
Designed to be run by GitHub Actions on a daily cron schedule.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")
MAX_RESULTS = 50
ARXIV_API_URL = "https://export.arxiv.org/api/query"
OUTPUT_PATH = os.path.join(BASE_DIR, "data", "latest.json")


def load_categories() -> list[str]:
    """Load categories from config.yml (simple parser, no PyYAML needed)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    categories = []
    for line in lines:
        m = re.match(r'\s+-\s+(.+)', line)
        if m:
            categories.append(m.group(1).strip())
    if not categories:
        sys.exit("Error: no categories found in config.yml")
    return categories
REQUEST_INTERVAL = 3  # seconds between API requests

# Timezones
JST = timezone(timedelta(hours=9))

# Atom / OpenSearch namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def read_previous_date_to() -> Optional[str]:
    """Read date_to from the previous latest.json. Returns YYYYMMDD or None."""
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        dt = data.get("date_to")
        if dt:
            return dt.replace("-", "")
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        pass
    return None


def get_date_range(today_jst: datetime) -> Optional[tuple[str, str]]:
    """Return (date_from, date_to) as YYYYMMDD strings, or None if nothing to fetch."""
    weekday = today_jst.weekday()  # 0=Mon .. 6=Sun

    if weekday == 5 or weekday == 6:  # Sat or Sun — arXiv has no announcements
        return None

    yesterday = today_jst - timedelta(days=1)
    date_to = yesterday.strftime("%Y%m%d")

    # Search from the day after the previous fetch's end date
    prev = read_previous_date_to()
    if prev:
        prev_date = datetime.strptime(prev, "%Y%m%d")
        date_from = (prev_date + timedelta(days=1)).strftime("%Y%m%d")
        if date_from > date_to:
            return None  # Already up to date
    else:
        # Fallback: yesterday only
        date_from = date_to

    return (date_from, date_to)


def fetch_category(category: str, date_from: str, date_to: str) -> tuple[list[dict], int]:
    """Fetch papers for a single category. Returns (papers, total_results)."""
    # Build submittedDate filter: [YYYYMMDD0000+TO+YYYYMMDD2359]
    date_filter = f"[{date_from}0000+TO+{date_to}2359]"

    params = {
        "search_query": f"cat:{category}+AND+submittedDate:{date_filter}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(MAX_RESULTS),
    }

    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params, safe='+:[]')}"
    print(f"Fetching: {url}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "daily-arxiv-bot/1.0 (https://github.com/RintaroMasaoka/daily-arxiv)")

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()

    root = ET.fromstring(data)

    # Total results from OpenSearch
    total_el = root.find("opensearch:totalResults", NS)
    total_results = int(total_el.text) if total_el is not None else 0

    papers = []
    for entry in root.findall("atom:entry", NS):
        # Skip the arXiv API "boilerplate" entry that has no id with abs/
        entry_id = entry.find("atom:id", NS)
        if entry_id is None:
            continue
        raw_id = entry_id.text.strip()
        if "/abs/" not in raw_id:
            continue

        # Extract arXiv ID (e.g., "2604.12345" from "http://arxiv.org/abs/2604.12345v1")
        arxiv_id = raw_id.split("/abs/")[-1]
        # Remove version suffix
        if arxiv_id and arxiv_id[-1].isdigit() and "v" in arxiv_id:
            arxiv_id = arxiv_id.rsplit("v", 1)[0]

        title = entry.find("atom:title", NS)
        title_text = " ".join(title.text.split()) if title is not None and title.text else ""

        summary = entry.find("atom:summary", NS)
        abstract = " ".join(summary.text.split()) if summary is not None and summary.text else ""

        authors = []
        for author in entry.findall("atom:author", NS):
            name = author.find("atom:name", NS)
            if name is not None and name.text:
                authors.append(name.text.strip())

        categories = []
        for cat in entry.findall("atom:category", NS):
            term = cat.get("term")
            if term:
                categories.append(term)

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title_text,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
        })

    return papers, total_results


def deduplicate(papers: list[dict]) -> list[dict]:
    """Remove duplicate papers by arXiv ID, keeping first occurrence."""
    seen = set()
    unique = []
    for p in papers:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)
    return unique


def main():
    now_jst = datetime.now(JST)
    print(f"Current time (JST): {now_jst.isoformat()}")

    date_range = get_date_range(now_jst)

    if date_range is None:
        print("Nothing to fetch (weekend or already up to date). Exiting.")
        return

    date_from, date_to = date_range
    date_from_fmt = f"{date_from[:4]}-{date_from[4:6]}-{date_from[6:]}"
    date_to_fmt = f"{date_to[:4]}-{date_to[4:6]}-{date_to[6:]}"
    print(f"Date range: {date_from_fmt} to {date_to_fmt}")

    all_papers = []
    total_results = {}

    categories = load_categories()
    print(f"Categories: {categories}")

    for i, category in enumerate(categories):
        if i > 0:
            print(f"Waiting {REQUEST_INTERVAL}s (rate limit)...")
            time.sleep(REQUEST_INTERVAL)

        papers, total = fetch_category(category, date_from, date_to)
        print(f"  {category}: {len(papers)} fetched, {total} total on arXiv")
        all_papers.extend(papers)
        total_results[category] = total

    all_papers = deduplicate(all_papers)
    print(f"After deduplication: {len(all_papers)} papers")

    if not all_papers:
        print("No papers found. Keeping previous data unchanged.")
        return

    result = {
        "fetched_at": now_jst.isoformat(),
        "date_from": date_from_fmt,
        "date_to": date_to_fmt,
        "categories_queried": categories,
        "total_results": total_results,
        "papers": all_papers,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(all_papers)} papers to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
