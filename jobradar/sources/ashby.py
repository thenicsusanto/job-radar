"""Ashby public job posting API.

Input:  a Board with ats == "ashby".
Output: one JobPosting per listed job.
Docs:   https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

from urllib.parse import quote

from ..boards import job_key
from ..http_client import fetch_json
from ..models import Board, JobPosting
from .greenhouse import parse_timestamp

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
MAX_DESCRIPTION_CHARACTERS = 30000


def parse_board_response(board: Board, payload: dict) -> list[JobPosting]:
    postings = []
    for raw_job in payload.get("jobs", []):
        if raw_job.get("isListed") is False:
            continue
        locations = [raw_job["location"]] if raw_job.get("location") else []
        for secondary_location in raw_job.get("secondaryLocations") or []:
            if secondary_location.get("location"):
                locations.append(secondary_location["location"])
        if raw_job.get("isRemote") and not any("remote" in place.lower() for place in locations):
            locations.append("Remote")
        postings.append(
            JobPosting(
                key=job_key("ashby", board.slug, str(raw_job["id"])),
                source="ashby",
                company_name=board.company_name,
                title=(raw_job.get("title") or "").strip(),
                url=raw_job.get("jobUrl") or raw_job.get("applyUrl") or "",
                locations=locations,
                posted_at=parse_timestamp(raw_job.get("publishedAt")),
                description=(raw_job.get("descriptionPlain") or "")[:MAX_DESCRIPTION_CHARACTERS],
                employment_type=raw_job.get("employmentType") or "",
                board_key=board.key,
            )
        )
    return postings


def fetch_board(board: Board) -> list[JobPosting]:
    return parse_board_response(board, fetch_json(API_URL.format(slug=quote(board.slug))))
