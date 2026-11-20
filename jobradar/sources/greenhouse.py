"""Greenhouse public job board API.

Input:  a Board with ats == "greenhouse".
Output: one JobPosting per open job on that board.
Docs:   https://developers.greenhouse.io/job-board.html
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from ..boards import job_key
from ..http_client import fetch_json
from ..models import Board, JobPosting

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
JOB_DETAIL_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
HTML_TAG = re.compile(r"<[^>]+>")
MAX_DESCRIPTION_CHARACTERS = 30000


def parse_timestamp(iso_text: str | None) -> float | None:
    if not iso_text:
        return None
    try:
        return datetime.fromisoformat(iso_text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_board_response(board: Board, payload: dict) -> list[JobPosting]:
    postings = []
    for raw_job in payload.get("jobs", []):
        location_name = (raw_job.get("location") or {}).get("name") or ""
        postings.append(
            JobPosting(
                key=job_key("greenhouse", board.slug, str(raw_job["id"])),
                source="greenhouse",
                company_name=board.company_name,
                title=(raw_job.get("title") or "").strip(),
                url=raw_job.get("absolute_url") or "",
                locations=[location_name] if location_name else [],
                posted_at=parse_timestamp(
                    raw_job.get("first_published") or raw_job.get("updated_at")
                ),
                board_key=board.key,
            )
        )
    return postings


def fetch_board(board: Board) -> list[JobPosting]:
    return parse_board_response(board, fetch_json(API_URL.format(slug=board.slug)))


def description_from_detail(payload: dict) -> str:
    """Greenhouse returns the description as entity-escaped HTML in "content"."""
    raw_html = html.unescape(payload.get("content") or "")
    return re.sub(r"\s+", " ", HTML_TAG.sub(" ", raw_html)).strip()[:MAX_DESCRIPTION_CHARACTERS]


def fetch_description(job_key_text: str) -> str:
    """Input: a key like "greenhouse:acme:123". Output: that job's plain-text description.

    The board listing omits descriptions, so the poller calls this only for
    brand-new internship postings (a handful per run), not for every job.
    """
    _ats_name, slug, job_id = job_key_text.split(":", 2)
    return description_from_detail(fetch_json(JOB_DETAIL_URL.format(slug=slug, job_id=job_id)))
