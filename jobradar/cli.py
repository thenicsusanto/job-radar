"""Command line entry point.

    python -m jobradar poll        check every source, email strong new matches
    python -m jobradar digest      email the queued weaker matches, then clear the queue
    python -m jobradar discover    refresh the board watchlist and company directory
    python -m jobradar test-email  send a sample email to confirm SMTP works
"""

from __future__ import annotations

import argparse
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import discovery, emailer
from . import state as state_store
from .boards import load_boards, parse_ats_url, save_boards
from .http_client import NotFound, NotModified
from .models import Board, JobPosting, ScoredJob
from .scoring import is_internship, score_job
from .sources import fetch_board, hackernews, trackers

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPOSITORY_ROOT / "config" / "profile.toml"
EXTRA_COMPANIES_PATH = REPOSITORY_ROOT / "config" / "extra_companies.txt"
BOARDS_PATH = REPOSITORY_ROOT / "data" / "boards.json"
DIRECTORY_PATH = REPOSITORY_ROOT / "data" / "company_directory.json"
DEFAULT_STATE_PATH = REPOSITORY_ROOT / "state" / "state.json"
BOARD_POLL_WORKERS = 24
BASELINE_EMAIL_JOB_COUNT = 25


def load_profile() -> dict:
    with PROFILE_PATH.open("rb") as profile_file:
        return tomllib.load(profile_file)


def fetch_board_safely(board: Board) -> tuple[Board, list[JobPosting] | None, str]:
    try:
        return board, fetch_board(board), ""
    except NotFound:
        return board, None, "board not found (404)"
    except (OSError, ValueError, KeyError, TypeError) as fetch_error:
        return board, None, str(fetch_error)


def collect_postings(profile: dict, boards: list[Board], state: dict) -> tuple[list[JobPosting], list[str], dict]:
    """Fetch every source. Returns (postings, board keys that answered, pending state updates)."""
    postings: list[JobPosting] = []
    responding_board_keys: list[str] = []
    pending_updates = {"tracker_etags": {}, "hackernews_examined_ids": None}

    active_boards = [board for board in boards if not state_store.board_is_disabled(state, board.key)]
    with ThreadPoolExecutor(max_workers=BOARD_POLL_WORKERS) as executor:
        for board, board_postings, error_text in executor.map(fetch_board_safely, active_boards):
            state_store.record_board_result(state, board.key, succeeded=board_postings is not None)
            if board_postings is None:
                print(f"board failed: {board.key}: {error_text}")
                continue
            responding_board_keys.append(board.key)
            postings.extend(board_postings)

    for tracker in profile.get("trackers", []):
        try:
            tracker_postings, new_etag = trackers.fetch_tracker(
                tracker["name"], tracker["url"], state["tracker_etags"].get(tracker["name"])
            )
            postings.extend(tracker_postings)
            if new_etag:
                pending_updates["tracker_etags"][tracker["name"]] = new_etag
        except NotModified:
            pass
        except (NotFound, OSError, ValueError) as fetch_error:
            print(f"tracker failed: {tracker['name']}: {fetch_error}")

    try:
        hackernews_postings, examined_ids = hackernews.fetch_new_job_stories(
            set(state["hackernews_examined_ids"])
        )
        postings.extend(hackernews_postings)
        pending_updates["hackernews_examined_ids"] = examined_ids
    except (NotFound, OSError, ValueError, KeyError, TypeError) as fetch_error:
        print(f"hackernews failed: {fetch_error}")

    print(f"polled {len(active_boards)} boards ({len(responding_board_keys)} ok), {len(postings)} postings total")
    return postings, responding_board_keys, pending_updates


def select_new_internships(postings: list[JobPosting], profile: dict, state: dict, now: float) -> list[JobPosting]:
    """Internship postings we have not seen before, de-duplicated within this run."""
    new_internships = []
    keys_this_run: set[str] = set()
    fingerprints_this_run: set[str] = set()
    for posting in postings:  # ATS postings come first, so they win over tracker copies
        if not is_internship(posting, profile):
            continue
        posting_fingerprint = state_store.fingerprint(posting)
        if posting.key in keys_this_run or posting_fingerprint in fingerprints_this_run:
            continue
        keys_this_run.add(posting.key)
        fingerprints_this_run.add(posting_fingerprint)
        if state_store.is_new(state, posting, now):
            new_internships.append(posting)
    return new_internships


def run_poll(state_path: Path, dry_run: bool) -> int:
    profile = load_profile()
    boards = load_boards(BOARDS_PATH)
    company_directory = discovery.load_directory(DIRECTORY_PATH)
    state = state_store.load_state(state_path)
    now = time.time()
    alert_rules = profile["alerts"]

    postings, responding_board_keys, pending_updates = collect_postings(profile, boards, state)
    new_internships = select_new_internships(postings, profile, state, now)
    scored_jobs = [score_job(posting, profile, company_directory, date.today()) for posting in new_internships]
    matches = sorted(
        (scored for scored in scored_jobs if not scored.excluded_because and scored.score >= alert_rules["digest_threshold"]),
        key=lambda scored: scored.score,
        reverse=True,
    )

    is_first_run = state["bootstrapped_at"] is None
    known_board_keys = set(state["known_board_keys"])
    instant_jobs: list[ScoredJob] = []
    digest_jobs: list[ScoredJob] = []
    if is_first_run:
        # Everything open today is "new" on the first run. Send one summary, not a flood.
        baseline_jobs = matches[:BASELINE_EMAIL_JOB_COUNT]
        if baseline_jobs:
            emailer.send_email(
                "baseline",
                "Job radar is running. These are the strongest matches open right now; "
                "from here on you only hear about new postings.",
                baseline_jobs,
                dry_run,
            )
    else:
        for scored in matches:
            board_key = scored.job.board_key
            from_newly_tracked_board = board_key is not None and board_key not in known_board_keys
            if scored.score >= alert_rules["instant_threshold"] and not from_newly_tracked_board:
                instant_jobs.append(scored)
            else:
                digest_jobs.append(scored)
        overflow = instant_jobs[alert_rules["max_jobs_per_instant_email"]:]
        instant_jobs = instant_jobs[: alert_rules["max_jobs_per_instant_email"]]
        digest_jobs.extend(overflow)
        if instant_jobs:
            # If sending fails this raises before state is saved, so the next run retries.
            emailer.send_email("instant", "New internship postings that match your profile:", instant_jobs, dry_run)

    for posting in new_internships:
        state_store.mark_seen(state, posting, now)
    state["digest_queue"].extend(scored.to_dict() for scored in digest_jobs)
    state["known_board_keys"] = sorted(known_board_keys | set(responding_board_keys))
    state["tracker_etags"].update(pending_updates["tracker_etags"])
    if pending_updates["hackernews_examined_ids"] is not None:
        state["hackernews_examined_ids"] = pending_updates["hackernews_examined_ids"]
    if is_first_run:
        state["bootstrapped_at"] = int(now)
    state_store.save_state(state_path, state)

    print(
        f"new internships: {len(new_internships)}, matches: {len(matches)}, "
        f"instant: {len(instant_jobs)}, queued for digest: {len(digest_jobs)}"
        + (" (first run: baseline only)" if is_first_run else "")
    )
    return 0


def run_digest(state_path: Path, dry_run: bool) -> int:
    state = state_store.load_state(state_path)
    queued_jobs = sorted(
        (ScoredJob.from_dict(payload) for payload in state["digest_queue"]),
        key=lambda scored: scored.score,
        reverse=True,
    )
    if not queued_jobs:
        print("digest queue is empty; nothing to send")
        return 0
    disabled_board_count = sum(
        1 for failure_count in state["board_failure_counts"].values()
        if failure_count >= state_store.DISABLE_BOARD_AFTER_FAILURES
    )
    intro = "Weaker or secondary matches since the last digest, best first."
    if disabled_board_count:
        intro += f" ({disabled_board_count} boards are paused after repeated failures; the weekly discovery run rechecks them.)"
    emailer.send_email("digest", intro, queued_jobs, dry_run)
    state["digest_queue"] = []
    state_store.save_state(state_path, state)
    print(f"digest sent with {len(queued_jobs)} jobs")
    return 0


def run_discover(state_path: Path, skip_probe: bool) -> int:
    profile = load_profile()
    boards, company_directory, summary = discovery.run_discovery(
        load_boards(BOARDS_PATH), profile.get("trackers", []), EXTRA_COMPANIES_PATH, skip_probe
    )
    save_boards(BOARDS_PATH, boards)
    discovery.save_directory(DIRECTORY_PATH, company_directory)
    # Give paused boards another chance after each discovery run.
    state = state_store.load_state(state_path)
    if state["board_failure_counts"]:
        state["board_failure_counts"] = {}
        state_store.save_state(state_path, state)
    print(f"discovery summary: {summary}")
    return 0


def run_test_email(dry_run: bool) -> int:
    sample_job = JobPosting(
        key="sample:1", source="sample", company_name="Example Robotics",
        title="Reinforcement Learning Intern (Summer 2027)", url="https://example.com/jobs/1",
        locations=["Seattle, WA"], posted_at=time.time() - 240,
    )
    sample_scored_job = ScoredJob(job=sample_job, score=100, reasons=["sample alert to confirm email delivery"])
    emailer.send_email("instant", "This is a test alert from job radar.", [sample_scored_job], dry_run)
    print("test email sent")
    return 0


def main(argument_list: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobradar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["poll", "digest", "discover", "test-email"])
    parser.add_argument("--dry-run", action="store_true", help="print emails instead of sending them")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--skip-probe", action="store_true", help="discover: skip guessing slugs for directory companies")
    arguments = parser.parse_args(argument_list)
    if arguments.command == "poll":
        return run_poll(arguments.state_path, arguments.dry_run)
    if arguments.command == "digest":
        return run_digest(arguments.state_path, arguments.dry_run)
    if arguments.command == "discover":
        return run_discover(arguments.state_path, arguments.skip_probe)
    return run_test_email(arguments.dry_run)


if __name__ == "__main__":
    sys.exit(main())
