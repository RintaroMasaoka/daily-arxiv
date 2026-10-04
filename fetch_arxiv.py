#!/usr/bin/env python3
"""Fetch recent arXiv papers from cond-mat.str-el and cond-mat.stat-mech.

Queries the arXiv API (export.arxiv.org) and writes results to data/latest.json.
GitHub Actions uses urllib by default; the scheduled task can use curl for recovery.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.parser import Parser
from http import HTTPStatus
from pathlib import Path
from typing import Optional

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yml")
MAX_RESULTS = 100
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
RETRY_DELAYS = (15, 30, 60, 120)  # five attempts for transient API errors (503, etc.)
MAX_RETRIES = len(RETRY_DELAYS) + 1
# arXiv has returned 406 transiently, despite its usual content-negotiation meaning.
RETRYABLE_HTTP_STATUSES = (406, 429, 500, 503)

# Timezones
JST = timezone(timedelta(hours=9))

# Atom / OpenSearch namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class FetchError(RuntimeError):
    """An arXiv response could not be fetched or validated."""


def fetch_with_curl(req: urllib.request.Request) -> tuple[int, bytes]:
    """Use curl in the task environment while preserving HTTP diagnostics."""
    with tempfile.TemporaryDirectory(prefix="arxiv-curl-") as directory:
        body_path = os.path.join(directory, "body")
        headers_path = os.path.join(directory, "headers")
        command = [
            "curl", "--globoff", "--silent", "--show-error", "--location",
            "--connect-timeout", "10", "--max-time", "60",
            "--dump-header", headers_path, "--output", body_path,
            "--write-out", "%{http_code}",
        ]
        for name, value in req.header_items():
            command.extend(("--header", f"{name}: {value}"))
        command.append(req.full_url)

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as error:
            raise urllib.error.URLError(f"curl could not start: {error}") from error

        body = Path(body_path).read_bytes() if os.path.exists(body_path) else b""
        raw_headers = Path(headers_path).read_text(encoding="iso-8859-1") if os.path.exists(headers_path) else ""
        blocks = re.split(r"\r?\n\r?\n", raw_headers)
        final_block = next((block for block in reversed(blocks) if block.startswith("HTTP/")), "")
        headers = Parser().parsestr("\n".join(final_block.splitlines()[1:]))

        if result.returncode == 6:
            raise FetchError(f"curl DNS resolution failed: {result.stderr.strip()[:300]}")
        if result.returncode != 0:
            raise urllib.error.URLError(f"curl exit {result.returncode}: {result.stderr.strip()[:300]}")
        try:
            status = int(result.stdout.strip())
        except ValueError as error:
            raise urllib.error.URLError(f"curl returned invalid HTTP status: {result.stdout!r}") from error
        if status == 0:
            raise urllib.error.URLError("curl did not receive an HTTP response")
        if status != 200:
            try:
                reason = HTTPStatus(status).phrase
            except ValueError:
                reason = "HTTP error"
            raise urllib.error.HTTPError(req.full_url, status, reason, headers, io.BytesIO(body))
        return status, body


def read_previous() -> tuple[Optional[str], set[str]]:
    """Read date_to and paper IDs from previous latest.json.

    Returns (date_to as YYYYMMDD or None, set of arxiv_ids).
    """
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        dt = data.get("date_to")
        ids = {p["arxiv_id"] for p in data.get("papers", [])}
        return (dt.replace("-", "") if dt else None, ids)
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return (None, set())


def get_date_range(today_jst: datetime) -> Optional[tuple[str, str]]:
    """Return (date_from, date_to) as YYYYMMDD strings, or None if nothing to fetch."""
    # Use 2-day offset because cron runs at 20:00 UTC (= 05:00 JST next day).
    # Papers submitted on day X are indexed in the arXiv API by ~14:00 UTC day X+1.
    # At 20:00 UTC day X, only day X-1 papers are reliably available.
    target = today_jst - timedelta(days=2)
    date_to = target.strftime("%Y%m%d")

    # Re-query from prev_date_to (1-day overlap) to catch papers that were
    # submitted on that day but not yet indexed at the time of the last fetch.
    # This handles Friday afternoon submissions (indexed Tuesday), holidays, etc.
    prev, _ = read_previous()
    print(f"Date calc: today={today_jst.strftime('%Y-%m-%d %H:%M %Z')}, "
          f"target={target.strftime('%Y-%m-%d')}, prev_date_to={prev}")
    if prev:
        date_from = prev  # overlap: re-query the last date
        if prev > date_to:
            print(f"  Skip: prev_date_to={prev} > date_to={date_to}")
            return None  # Already up to date
    else:
        # Fallback: target date only
        date_from = date_to

    return (date_from, date_to)


def fetch_category(category: str, date_from: str, date_to: str,
                   transport: str = "urllib") -> tuple[list[dict], int]:
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
    req.add_header("Accept", "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8")
    req.add_header("Accept-Encoding", "identity")
    req.add_header("Connection", "close")

    data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if transport == "curl":
                status, data = fetch_with_curl(req)
            elif transport == "urllib":
                with urllib.request.urlopen(req, timeout=60) as resp:
                    status, data = resp.status, resp.read()
            else:
                raise ValueError(f"Unknown transport: {transport}")
            print(f"  HTTP {status}, {len(data)} bytes")
            break
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", errors="replace")
            e.close()
            diagnostic_headers = {
                name: e.headers.get(name)
                for name in ("Server", "Via", "X-Cache", "Retry-After")
                if e.headers and e.headers.get(name)
            }
            print(f"  ERROR (attempt {attempt}/{MAX_RETRIES}): HTTP {e.code} {e.reason}"
                  f" | body: {body!r} | headers: {diagnostic_headers}")
            if e.code in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRIES:
                wait = RETRY_DELAYS[attempt - 1]
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise FetchError(
                f"{category} {date_from}: HTTP {e.code} {e.reason} after {attempt} attempts"
                f"; headers={diagnostic_headers}; body={body!r}"
            ) from e
        except urllib.error.URLError as e:
            print(f"  ERROR (attempt {attempt}/{MAX_RETRIES}): {e.reason}")
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAYS[attempt - 1]
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise FetchError(f"{category} {date_from}: {e.reason} after {attempt} attempts") from e
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            raise FetchError(f"{category} {date_from}: {type(e).__name__}: {e}") from e

    if data is None:
        raise FetchError(f"{category} {date_from}: no response from arXiv")

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"  ERROR: XML parse failed: {e}")
        print(f"  Response body (first 500 chars): {data[:500].decode('utf-8', errors='replace')}")
        raise FetchError(f"{category} {date_from}: invalid XML response") from e

    if root.tag != f"{{{NS['atom']}}}feed":
        raise FetchError(f"{category} {date_from}: response is not an Atom feed")

    # Total results from OpenSearch
    total_el = root.find("opensearch:totalResults", NS)
    if total_el is None or total_el.text is None:
        raise FetchError(f"{category} {date_from}: response has no totalResults")
    try:
        total_results = int(total_el.text)
    except ValueError as e:
        raise FetchError(f"{category} {date_from}: invalid totalResults") from e
    print(f"  totalResults={total_results}")

    papers = []
    entries_total = 0
    entries_skipped = 0
    for entry in root.findall("atom:entry", NS):
        entries_total += 1
        # Skip the arXiv API "boilerplate" entry that has no id with abs/
        entry_id = entry.find("atom:id", NS)
        if entry_id is None:
            entries_skipped += 1
            continue
        raw_id = entry_id.text.strip()
        if "/abs/" not in raw_id:
            entries_skipped += 1
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

    print(f"  Entries: {entries_total} found, {entries_skipped} skipped, {len(papers)} parsed")
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


def main(transport: str = "urllib"):
    now_jst = datetime.now(JST)
    print(f"Current time (JST): {now_jst.isoformat()}")

    date_range = get_date_range(now_jst)

    if date_range is None:
        print("Nothing to fetch (already up to date). Exiting.")
        print(f"  prev_date_to in latest.json: {read_previous()[0]}")
        return

    date_from, date_to = date_range
    date_from_fmt = f"{date_from[:4]}-{date_from[4:6]}-{date_from[6:]}"
    date_to_fmt = f"{date_to[:4]}-{date_to[4:6]}-{date_to[6:]}"
    print(f"Date range: {date_from_fmt} to {date_to_fmt}")

    all_papers = []
    total_results = {}

    categories = load_categories()
    print(f"Categories: {categories}")

    # Build list of individual dates to query (1 day at a time to reduce
    # the chance of hitting the 100-paper-per-request limit).
    from_dt = datetime.strptime(date_from, "%Y%m%d")
    to_dt = datetime.strptime(date_to, "%Y%m%d")
    dates = []
    d = from_dt
    while d <= to_dt:
        dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)

    request_count = 0
    empty_queries = 0
    for single_date in dates:
        for category in categories:
            if request_count > 0:
                print(f"Waiting {REQUEST_INTERVAL}s (rate limit)...")
                time.sleep(REQUEST_INTERVAL)

            papers, total = fetch_category(category, single_date, single_date, transport=transport)
            date_fmt = f"{single_date[:4]}-{single_date[4:6]}-{single_date[6:]}"
            print(f"  {category} ({date_fmt}): {len(papers)} fetched, {total} total on arXiv")
            if total == 0 and len(papers) == 0:
                empty_queries += 1
            all_papers.extend(papers)
            # Accumulate totals per category across all dates
            total_results[category] = total_results.get(category, 0) + total
            request_count += 1

    all_papers = deduplicate(all_papers)
    print(f"After deduplication: {len(all_papers)} papers ({empty_queries}/{request_count} queries returned 0)")

    if not all_papers:
        print("No papers found. Keeping previous data unchanged.")
        return

    # Only update latest.json if there are papers not seen in the previous fetch.
    # This prevents date_to from advancing when only duplicate papers are found
    # in the overlap window, ensuring late-indexed papers are re-queried.
    _, prev_ids = read_previous()
    new_ids = {p["arxiv_id"] for p in all_papers} - prev_ids
    if not new_ids:
        print(f"No new papers (all {len(all_papers)} already in previous fetch). "
              "Keeping previous data unchanged.")
        return
    print(f"  {len(new_ids)} new papers found")

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("urllib", "curl"), default="urllib")
    main(transport=parser.parse_args().transport)
