"""Lever public postings API.

Input:  a Board with ats == "lever".
Output: one JobPosting per open posting.
Docs:   https://github.com/lever/postings-api
"""

from __future__ import annotations

from urllib.parse import quote

from ..boards import job_key
from ..http_client import fetch_json
from ..models import Board, JobPosting

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
MAX_DESCRIPTION_CHARACTERS = 6000


def parse_board_response(board: Board, payload: list) -> list[JobPosting]:
    postings = []
    for raw_job in payload or []:
        categories = raw_job.get("categories") or {}
        locations = categories.get("allLocations") or (
            [categories["location"]] if categories.get("location") else []
        )
        created_at_milliseconds = raw_job.get("createdAt")
        postings.append(
            JobPosting(
                key=job_key("lever", board.slug, str(raw_job["id"])),
                source="lever",
                company_name=board.company_name,
                title=(raw_job.get("text") or "").strip(),
                url=raw_job.get("hostedUrl") or "",
                locations=list(locations),
                posted_at=created_at_milliseconds / 1000 if created_at_milliseconds else None,
                description=(raw_job.get("descriptionPlain") or "")[:MAX_DESCRIPTION_CHARACTERS],
                employment_type=categories.get("commitment") or "",
                board_key=board.key,
            )
        )
    return postings


def fetch_board(board: Board) -> list[JobPosting]:
    return parse_board_response(board, fetch_json(API_URL.format(slug=quote(board.slug))))
