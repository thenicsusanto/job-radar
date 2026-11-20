"""Community internship trackers on GitHub (SimplifyJobs, vanshb03, ...).

These repos keep a machine-readable listings.json behind their README tables.
They lag the real posting, but they cover companies whose career sites we
cannot poll directly (Workday, custom sites, big tech).

Input:  a tracker config {name, url} and the ETag from the previous fetch.
Output: (postings, new_etag). Raises NotModified when nothing changed.
"""

from __future__ import annotations

import json
import time

from ..boards import job_key, parse_ats_url
from ..http_client import fetch
from ..models import JobPosting

MAX_LISTING_AGE_DAYS = 10


def parse_listings(tracker_name: str, raw_listings: list, now: float | None = None) -> list[JobPosting]:
    now = now or time.time()
    oldest_allowed = now - MAX_LISTING_AGE_DAYS * 86400
    postings = []
    for raw_listing in raw_listings:
        if not raw_listing.get("active", True) or not raw_listing.get("is_visible", True):
            continue
        posted_at = raw_listing.get("date_posted") or 0
        if posted_at < oldest_allowed:
            continue
        url = raw_listing.get("url") or ""
        # When the tracker links straight to an ATS job, reuse the ATS key so the
        # same job found by both the tracker and our own poller is alerted once.
        parsed_url = parse_ats_url(url)
        if parsed_url and parsed_url[2]:
            key = job_key(*parsed_url)
        else:
            key = f"{tracker_name}:{raw_listing.get('id')}"
        terms = list(raw_listing.get("terms") or [])
        if raw_listing.get("season"):
            terms.append(str(raw_listing["season"]))
        postings.append(
            JobPosting(
                key=key,
                source=tracker_name,
                company_name=(raw_listing.get("company_name") or "").strip(),
                title=(raw_listing.get("title") or "").strip(),
                url=url,
                locations=list(raw_listing.get("locations") or []),
                posted_at=float(posted_at),
                terms=[term for term in terms if term and term != "N/A"],
                degrees=list(raw_listing.get("degrees") or []),
            )
        )
    return postings


def fetch_tracker(tracker_name: str, url: str, etag: str | None) -> tuple[list[JobPosting], str | None]:
    body, new_etag = fetch(url, etag=etag, timeout_seconds=60)
    return parse_listings(tracker_name, json.loads(body)), new_etag
