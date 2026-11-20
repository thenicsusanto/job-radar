"""Shared data shapes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Board:
    """One company's public job board on an applicant tracking system."""

    ats: str  # "greenhouse" | "lever" | "ashby"
    slug: str
    company_name: str
    discovered_via: str = "manual"

    @property
    def key(self) -> str:
        return f"{self.ats}:{self.slug.lower()}"


@dataclass
class JobPosting:
    key: str  # stable unique id, e.g. "greenhouse:stripe:12345"
    source: str  # where we found it: an ATS name, "simplify", "vanshb03", "hackernews"
    company_name: str
    title: str
    url: str
    locations: list[str] = field(default_factory=list)
    posted_at: float | None = None  # unix seconds, when the source provides it
    description: str = ""
    employment_type: str = ""
    terms: list[str] = field(default_factory=list)
    degrees: list[str] = field(default_factory=list)
    board_key: str | None = None


@dataclass
class ScoredJob:
    job: JobPosting
    score: int
    reasons: list[str]
    excluded_because: str | None = None

    def to_dict(self) -> dict:
        return {
            "job": {**asdict(self.job), "description": ""},  # keep state/state.json small
            "score": self.score,
            "reasons": self.reasons,
            "excluded_because": self.excluded_because,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ScoredJob":
        return cls(
            job=JobPosting(**payload["job"]),
            score=payload["score"],
            reasons=payload["reasons"],
            excluded_because=payload.get("excluded_because"),
        )
