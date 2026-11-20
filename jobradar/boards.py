"""The watchlist of ATS boards, and helpers for recognising ATS URLs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

from .models import Board

GREENHOUSE_URL = re.compile(
    r"https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/"
    r"(?:embed/job_app\?(?:[^#]*&)?for=)?(?P<slug>[A-Za-z0-9_.-]+)"
    r"(?:/jobs/(?P<job_id>\d+))?",
    re.IGNORECASE,
)
ASHBY_URL = re.compile(
    r"https?://jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)(?:/(?P<job_id>[0-9a-f-]{36}))?",
    re.IGNORECASE,
)
LEVER_URL = re.compile(
    r"https?://jobs\.(?:eu\.)?lever\.co/(?P<slug>[^/?#]+)(?:/(?P<job_id>[0-9a-f-]{36}))?",
    re.IGNORECASE,
)
URL_PATTERNS = {"greenhouse": GREENHOUSE_URL, "ashby": ASHBY_URL, "lever": LEVER_URL}
SLUGS_THAT_ARE_NOT_COMPANIES = {"embed", "jobs", "job_app", "internal"}


def parse_ats_url(url: str) -> tuple[str, str, str | None] | None:
    """Return (ats, slug, job_id) when the URL points at a supported ATS board."""
    for ats_name, pattern in URL_PATTERNS.items():
        match = pattern.search(url or "")
        if not match:
            continue
        slug = unquote(match.group("slug"))
        if slug.lower() in SLUGS_THAT_ARE_NOT_COMPANIES:
            return None
        return ats_name, slug, match.group("job_id")
    return None


def job_key(ats: str, slug: str, job_id: str) -> str:
    return f"{ats}:{slug.lower()}:{job_id}"


def load_boards(boards_path: Path) -> list[Board]:
    if not boards_path.exists():
        return []
    return [Board(**entry) for entry in json.loads(boards_path.read_text())]


def save_boards(boards_path: Path, boards: list[Board]) -> None:
    ordered = sorted(boards, key=lambda board: (board.company_name.lower(), board.ats))
    entries = [
        {
            "ats": board.ats,
            "slug": board.slug,
            "company_name": board.company_name,
            "discovered_via": board.discovered_via,
        }
        for board in ordered
    ]
    boards_path.parent.mkdir(parents=True, exist_ok=True)
    boards_path.write_text(json.dumps(entries, indent=1) + "\n")
