"""Hacker News job stories: YC startups post "X (YC S25) Is Hiring ..." here,
often before the role shows up anywhere else.

Input:  the set of HN item ids already examined on earlier runs.
Output: (postings, examined_ids). Postings are every unexamined job story; the
        internship filter downstream decides which ones matter.
"""

from __future__ import annotations

import html
import re

from ..http_client import fetch_json
from ..models import JobPosting

JOB_STORIES_URL = "https://hacker-news.firebaseio.com/v0/jobstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
COMPANY_FROM_TITLE = re.compile(r"^(?P<company>.+?)\s*(?:\(YC [A-Z]\d{2}\)|is hiring|hiring)", re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")


def parse_item(raw_item: dict) -> JobPosting | None:
    title = (raw_item.get("title") or "").strip()
    if not title:
        return None
    company_match = COMPANY_FROM_TITLE.match(title)
    company_name = company_match.group("company").strip() if company_match else title
    item_id = raw_item["id"]
    return JobPosting(
        key=f"hackernews:{item_id}",
        source="hackernews",
        company_name=company_name,
        title=title,
        url=raw_item.get("url") or f"https://news.ycombinator.com/item?id={item_id}",
        posted_at=raw_item.get("time"),
        description=html.unescape(HTML_TAG.sub(" ", raw_item.get("text") or ""))[:6000],
    )


def fetch_new_job_stories(already_examined_ids: set[int]) -> tuple[list[JobPosting], list[int]]:
    current_ids = fetch_json(JOB_STORIES_URL) or []
    postings = []
    for item_id in current_ids:
        if item_id in already_examined_ids:
            continue
        raw_item = fetch_json(ITEM_URL.format(item_id=item_id))
        if raw_item:
            posting = parse_item(raw_item)
            if posting:
                postings.append(posting)
    return postings, list(current_ids)
