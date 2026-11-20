"""Persistent memory between runs: which jobs we have already seen, and the
digest queue. Stored as JSON and committed back to the repo by the workflow."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .models import JobPosting

FINGERPRINT_WINDOW_DAYS = 21
DISABLE_BOARD_AFTER_FAILURES = 12


def empty_state() -> dict:
    return {
        "version": 1,
        "bootstrapped_at": None,
        "seen_job_keys": {},  # job key -> unix time first seen
        "seen_fingerprints": {},  # "company|title" -> unix time last seen
        "known_board_keys": [],
        "board_failure_counts": {},
        "digest_queue": [],  # list of ScoredJob dicts
        "hackernews_examined_ids": [],
        "tracker_etags": {},
    }


def load_state(state_path: Path) -> dict:
    state = empty_state()
    if state_path.exists():
        state.update(json.loads(state_path.read_text()))
    return state


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def fingerprint(job: JobPosting) -> str:
    """Company + the set of words in the title, so the same role found via two
    sources (which often punctuate or repeat title words differently) alerts once."""
    company = re.sub(r"[^a-z0-9]", "", job.company_name.lower())
    title_words = sorted(set(re.findall(r"[a-z0-9]+", job.title.lower())))
    return f"{company}|{' '.join(title_words)}"


def is_new(state: dict, job: JobPosting, now: float | None = None) -> bool:
    now = now or time.time()
    if job.key in state["seen_job_keys"]:
        return False
    last_seen_fingerprint = state["seen_fingerprints"].get(fingerprint(job))
    if last_seen_fingerprint and now - last_seen_fingerprint < FINGERPRINT_WINDOW_DAYS * 86400:
        return False
    return True


def mark_seen(state: dict, job: JobPosting, now: float | None = None) -> None:
    now = now or time.time()
    state["seen_job_keys"].setdefault(job.key, int(now))
    state["seen_fingerprints"][fingerprint(job)] = int(now)


def board_is_disabled(state: dict, board_key: str) -> bool:
    return state["board_failure_counts"].get(board_key, 0) >= DISABLE_BOARD_AFTER_FAILURES


def record_board_result(state: dict, board_key: str, succeeded: bool) -> None:
    failure_counts = state["board_failure_counts"]
    if succeeded:
        failure_counts.pop(board_key, None)
    else:
        failure_counts[board_key] = min(
            failure_counts.get(board_key, 0) + 1, DISABLE_BOARD_AFTER_FAILURES
        )
