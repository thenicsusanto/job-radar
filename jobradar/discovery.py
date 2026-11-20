"""Grow the watchlist automatically.

Three inputs feed it:
  1. Community tracker listings: every Greenhouse / Lever / Ashby link in them
     reveals a real board slug, so these boards are verified to exist.
  2. YC company lists (AI, ML, robotics tags) from the yc-oss mirror: builds the
     AI/startup company directory used for scoring, and gives names to probe.
  3. config/extra_companies.txt: hand-picked non-YC AI/robotics companies.

For names without a known board we probe each ATS with guessed slugs. A probe
hit is a guess that the slug belongs to that company (Ashby and Lever do not
return the company name), so probed boards are labelled discovered_via="probe".
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .boards import parse_ats_url
from .http_client import NotFound, fetch_json
from .models import Board
from .scoring import normalize_company_name
from .sources import fetch_board

YC_TAG_LIST_URL = "https://raw.githubusercontent.com/yc-oss/api/main/tags/{tag}.json"
YC_TAGS = [
    "artificial-intelligence", "machine-learning", "robotics", "generative-ai", "deep-learning",
    "computer-vision", "reinforcement-learning", "ai", "nlp", "autonomous-vehicles", "drones",
    "ai-assistant", "aiops", "llm", "robotic-process-automation", "hard-tech",
]
MAX_STARTUP_TEAM_SIZE = 1000
MAX_TRACKER_LISTING_AGE_DAYS = 540
PROBE_ORDER = ["ashby", "greenhouse", "lever"]
MIN_PROBE_SLUG_LENGTH = 4
UUID_LIKE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def harvest_boards_from_listings(tracker_name: str, raw_listings: list, now: float | None = None) -> list[Board]:
    """Input: raw tracker listings. Output: one Board per distinct ATS slug linked from a recent listing."""
    oldest_allowed = (now or time.time()) - MAX_TRACKER_LISTING_AGE_DAYS * 86400
    boards_by_key: dict[str, Board] = {}
    for raw_listing in raw_listings:
        if (raw_listing.get("date_posted") or 0) < oldest_allowed:
            continue
        parsed_url = parse_ats_url(raw_listing.get("url") or "")
        company_name = (raw_listing.get("company_name") or "").strip()
        if not parsed_url or not company_name:
            continue
        ats_name, slug, _job_id = parsed_url
        if UUID_LIKE.fullmatch(slug):
            continue  # a job id that landed where the company slug should be
        board = Board(ats=ats_name, slug=slug, company_name=company_name, discovered_via=f"tracker:{tracker_name}")
        boards_by_key.setdefault(board.key, board)
    return list(boards_by_key.values())


def directory_entries_from_yc(yc_companies: list) -> dict:
    """Input: yc-oss company records. Output: directory entries keyed by normalized name."""
    entries = {}
    for company in yc_companies:
        if company.get("status") not in (None, "Active", "Public"):
            continue
        team_size = company.get("team_size") or 0
        entries[normalize_company_name(company["name"])] = {
            "name": company["name"],
            "is_ai": True,
            "is_startup": team_size <= MAX_STARTUP_TEAM_SIZE and company.get("status") != "Public",
            "note": f"YC {company.get('batch', '')}".strip(),
            "is_hiring": bool(company.get("isHiring")),
            "slug_hint": company.get("slug") or "",
        }
    return entries


def directory_entries_from_extra_file(extra_companies_path: Path) -> dict:
    """File format: one company per line; append "| large" for big companies (no startup bonus)."""
    entries = {}
    if not extra_companies_path.exists():
        return entries
    for line in extra_companies_path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        company_name, _separator, flags = (part.strip() for part in line.partition("|"))
        entries[normalize_company_name(company_name)] = {
            "name": company_name,
            "is_ai": True,
            "is_startup": "large" not in flags.lower(),
            "note": "hand-listed",
            "is_hiring": True,
            "slug_hint": "",
        }
    return entries


def candidate_slugs(company_name: str, slug_hint: str) -> list[str]:
    lowered = company_name.lower().strip()
    candidates = [
        slug_hint,
        re.sub(r"[^a-z0-9]", "", lowered),
        re.sub(r"[^a-z0-9]+", "-", lowered).strip("-"),
    ]
    unique_candidates = []
    for candidate in candidates:
        if len(candidate) >= MIN_PROBE_SLUG_LENGTH and candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def probe_company(company_name: str, slug_hint: str) -> Board | None:
    """Try guessed slugs on each ATS; return the first board that exists and has jobs."""
    for slug in candidate_slugs(company_name, slug_hint):
        for ats_name in PROBE_ORDER:
            board = Board(ats=ats_name, slug=slug, company_name=company_name, discovered_via="probe")
            try:
                if fetch_board(board):
                    return board
            except (NotFound, OSError, ValueError, KeyError, TypeError):
                continue
    return None


def fetch_yc_companies() -> list:
    companies_by_id = {}
    for tag in YC_TAGS:
        try:
            for company in fetch_json(YC_TAG_LIST_URL.format(tag=tag), timeout_seconds=60):
                companies_by_id[company["id"]] = company
        except (NotFound, OSError, ValueError):
            continue
    return list(companies_by_id.values())


def run_discovery(
    existing_boards: list[Board],
    tracker_configs: list[dict],
    extra_companies_path: Path,
    skip_probe: bool = False,
) -> tuple[list[Board], dict, dict]:
    """Returns (all boards, company directory, summary counts)."""
    boards_by_key = {board.key: board for board in existing_boards}
    summary = {"boards_before": len(boards_by_key), "from_trackers": 0, "from_probe": 0}

    for tracker in tracker_configs:
        try:
            raw_listings = fetch_json(tracker["url"], timeout_seconds=90)
        except (NotFound, OSError, ValueError) as fetch_error:
            print(f"warning: could not read tracker {tracker['name']}: {fetch_error}")
            continue
        for board in harvest_boards_from_listings(tracker["name"], raw_listings):
            if board.key not in boards_by_key:
                boards_by_key[board.key] = board
                summary["from_trackers"] += 1

    directory = directory_entries_from_yc(fetch_yc_companies())
    directory.update(directory_entries_from_extra_file(extra_companies_path))

    if not skip_probe:
        names_with_boards = {normalize_company_name(board.company_name) for board in boards_by_key.values()}
        to_probe = [
            entry for normalized_name, entry in directory.items()
            if entry["is_hiring"] and normalized_name not in names_with_boards
        ]
        with ThreadPoolExecutor(max_workers=12) as executor:
            probe_results = executor.map(lambda entry: probe_company(entry["name"], entry["slug_hint"]), to_probe)
            for board in probe_results:
                if board and board.key not in boards_by_key:
                    boards_by_key[board.key] = board
                    summary["from_probe"] += 1

    scoring_directory = {
        normalized_name: {key: entry[key] for key in ("name", "is_ai", "is_startup", "note")}
        for normalized_name, entry in sorted(directory.items())
    }
    summary["boards_after"] = len(boards_by_key)
    summary["directory_companies"] = len(scoring_directory)
    return list(boards_by_key.values()), scoring_directory, summary


def save_directory(directory_path: Path, directory: dict) -> None:
    directory_path.parent.mkdir(parents=True, exist_ok=True)
    directory_path.write_text(json.dumps(directory, indent=1) + "\n")


def load_directory(directory_path: Path) -> dict:
    return json.loads(directory_path.read_text()) if directory_path.exists() else {}
