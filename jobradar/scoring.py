"""Decide whether a posting is an internship worth alerting on, and how strongly.

score_job(job, profile, company_directory, today) -> ScoredJob
    job:               a JobPosting
    profile:           parsed config/profile.toml
    company_directory: {normalized company name: {"is_ai": bool, "is_startup": bool}}
    today:             date used for the stale-term check
    returns:           ScoredJob with score, human-readable reasons, and
                       excluded_because set when the job should be dropped
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from .models import JobPosting, ScoredJob

US_STATE_ABBREVIATION = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)
US_SIGNAL = re.compile(
    r"\b(usa|u\.s\.a?\.?|united states|us|san francisco|sf|bay area|new york|nyc|seattle|boston|"
    r"austin|los angeles|chicago|palo alto|mountain view|sunnyvale|san jose|pittsburgh|"
    r"washington|denver|atlanta|san diego|bellevue|redmond|cambridge, ma)\b",
    re.IGNORECASE,
)
NON_US_SIGNAL = re.compile(
    r"\b(canada|toronto|vancouver|montreal|waterloo|ottawa|ontario|quebec|british columbia|"
    r"uk|united kingdom|england|london|ireland|dublin|germany|berlin|munich|france|paris|"
    r"netherlands|amsterdam|switzerland|zurich|spain|madrid|barcelona|italy|poland|warsaw|"
    r"sweden|stockholm|israel|tel aviv|india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|"
    r"gurgaon|chennai|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|japan|tokyo|"
    r"korea|seoul|singapore|australia|sydney|melbourne|brazil|mexico|uae|dubai|emea|apac|europe)\b",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(20\d\d)\b")
SHORT_YEAR_RANGE = re.compile(r"\b(20\d\d)\s*[-/]\s*(\d\d)\b")


@lru_cache(maxsize=None)
def compile_whole_word_patterns(patterns: tuple[str, ...]) -> re.Pattern:
    joined = "|".join(f"(?:{pattern})" for pattern in patterns)
    return re.compile(rf"(?<![a-z0-9])(?:{joined})(?![a-z0-9])", re.IGNORECASE)


def matches_any(text: str, patterns: list[str]) -> bool:
    return bool(patterns) and bool(compile_whole_word_patterns(tuple(patterns)).search(text))


def normalize_company_name(company_name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company_name.lower())


def is_internship(job: JobPosting, profile: dict) -> bool:
    if matches_any(job.title, profile["internship"]["title_patterns"]):
        return True
    return "intern" in job.employment_type.lower()


def latest_year_mentioned(job: JobPosting) -> int | None:
    text = " ".join([job.title, *job.terms])
    years = [int(year) for year in YEAR.findall(text)]
    for start_year, short_end_year in SHORT_YEAR_RANGE.findall(text):
        years.append(int(start_year[:2] + short_end_year))
    return max(years) if years else None


def earliest_useful_year(today: date) -> int:
    # From September on, recruiting is for next year's terms.
    return today.year + 1 if today.month >= 9 else today.year


def is_outside_us(job: JobPosting) -> bool:
    if not job.locations:
        return False
    location_text = " | ".join(job.locations)
    has_us_signal = bool(US_STATE_ABBREVIATION.search(location_text) or US_SIGNAL.search(location_text))
    return bool(NON_US_SIGNAL.search(location_text)) and not has_us_signal


def score_job(job: JobPosting, profile: dict, company_directory: dict, today: date) -> ScoredJob:
    def excluded(reason: str) -> ScoredJob:
        return ScoredJob(job=job, score=0, reasons=[], excluded_because=reason)

    exclusion_rules = profile["exclude"]
    if matches_any(job.title, exclusion_rules["title_patterns"]):
        return excluded("title is outside target roles or degree level")

    latest_year = latest_year_mentioned(job)
    if latest_year is not None and latest_year < earliest_useful_year(today):
        return excluded(f"term already passed ({latest_year})")

    if job.degrees and not set(job.degrees) & set(exclusion_rules["accepted_degrees"]):
        return excluded("requires a graduate degree")

    location_rules = profile["location"]
    if location_rules["exclude_non_us"] and is_outside_us(job):
        return excluded("outside the US")

    matching_groups = [
        group for group in profile["role_groups"] if matches_any(job.title, group["title_patterns"])
    ]
    best_group = max(matching_groups, key=lambda group: group["points"], default=None)
    has_strong_role_signal = best_group is not None and best_group["points"] >= 50
    if not has_strong_role_signal and matches_any(job.title, exclusion_rules["soft_title_patterns"]):
        return excluded("title is outside target roles")

    score = 0
    reasons = []
    if best_group:
        score += best_group["points"]
        reasons.append(f"{best_group['name']} role (+{best_group['points']})")
    else:
        score += profile["fallback"]["points"]
        reasons.append(f"internship, role unclear (+{profile['fallback']['points']})")

    company_facts = company_directory.get(normalize_company_name(job.company_name), {})
    company_bonus = profile["company_bonus"]
    if company_facts.get("is_ai"):
        score += company_bonus["ai_company"]
        reasons.append(f"AI/robotics company (+{company_bonus['ai_company']})")
    if company_facts.get("is_startup"):
        score += company_bonus["startup"]
        reasons.append(f"startup (+{company_bonus['startup']})")

    description_rules = profile["description_bonus"]
    if job.description:
        description_text = job.description.lower()
        keyword_hits = [keyword for keyword in description_rules["keywords"] if keyword in description_text]
        description_points = min(
            len(keyword_hits) * description_rules["points_per_keyword"], description_rules["max_points"]
        )
        if description_points:
            score += description_points
            reasons.append(f"description mentions {', '.join(keyword_hits[:4])} (+{description_points})")

    if matches_any(" | ".join(job.locations), location_rules["preferred_patterns"]):
        score += location_rules["preferred_bonus"]
        reasons.append(f"preferred location (+{location_rules['preferred_bonus']})")

    return ScoredJob(job=job, score=score, reasons=reasons)
