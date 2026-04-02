#!/usr/bin/env python3
"""Fetch recent papers from arXiv API for specified categories."""

import json
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ARXIV_API = "http://export.arxiv.org/api/query"
CATEGORIES = ["cond-mat.str-el", "cond-mat.stat-mech"]
MAX_RESULTS = 50
LOOKBACK_DAYS = 5


def fetch_category(category: str, date_from: str, date_to: str) -> list[dict]:
    """Fetch papers from a single arXiv category."""
    query = f"cat:{category}"
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": MAX_RESULTS,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "arxiv-digest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    papers = []
    for entry in root.findall("atom:entry", ns):
        arxiv_id_raw = entry.find("atom:id", ns).text.strip()
        arxiv_id = arxiv_id_raw.split("/abs/")[-1]
        # Remove version suffix (e.g., "2506.12345v1" -> "2506.12345")
        if "v" in arxiv_id:
            arxiv_id = arxiv_id[: arxiv_id.rfind("v")]

        title = " ".join(entry.find("atom:title", ns).text.split())

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.find("atom:name", ns).text.strip()
            authors.append(name)

        abstract = " ".join(entry.find("atom:summary", ns).text.split())

        categories = []
        for cat in entry.findall("atom:category", ns):
            categories.append(cat.attrib.get("term", ""))

        published = entry.find("atom:published", ns).text.strip()[:10]

        papers.append({
            "id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
            "published": published,
        })

    return papers


def main():
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    date_to = today.isoformat()

    all_papers = []
    seen_ids = set()

    for category in CATEGORIES:
        try:
            papers = fetch_category(category, date_from, date_to)
        except Exception as e:
            print(f"Warning: failed to fetch {category}: {e}", file=sys.stderr)
            continue

        for p in papers:
            if p["id"] not in seen_ids:
                seen_ids.add(p["id"])
                all_papers.append(p)

    json.dump(all_papers, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()