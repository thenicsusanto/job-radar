"""Render and send alert emails over SMTP.

Environment variables:
    SMTP_USERNAME, SMTP_PASSWORD   required to send (for Gmail: an app password)
    EMAIL_TO                       recipient; defaults to SMTP_USERNAME
    SMTP_HOST, SMTP_PORT           default smtp.gmail.com:465 (implicit TLS)
"""

from __future__ import annotations

import html
import os
import smtplib
import time
from email.message import EmailMessage

from .models import ScoredJob


def describe_age(posted_at: float | None, now: float | None = None) -> str:
    if not posted_at:
        return ""
    elapsed_seconds = max((now or time.time()) - posted_at, 0)
    if elapsed_seconds < 3600:
        return f"posted {int(elapsed_seconds // 60)} min ago"
    if elapsed_seconds < 86400:
        return f"posted {int(elapsed_seconds // 3600)} h ago"
    return f"posted {int(elapsed_seconds // 86400)} d ago"


def build_subject(kind: str, scored_jobs: list[ScoredJob]) -> str:
    if kind == "instant":
        top_job = scored_jobs[0].job
        extra_count = len(scored_jobs) - 1
        suffix = f" (+{extra_count} more)" if extra_count else ""
        return f"[New] {top_job.title} @ {top_job.company_name}{suffix}"
    if kind == "baseline":
        return f"[Job radar is live] {len(scored_jobs)} best currently-open matches"
    return f"[Digest] {len(scored_jobs)} more internship matches"


def render_plain_text(intro: str, scored_jobs: list[ScoredJob]) -> str:
    lines = [intro, ""]
    for scored_job in scored_jobs:
        job = scored_job.job
        details = [", ".join(job.locations[:3]) or "location not listed", describe_age(job.posted_at), f"via {job.source}"]
        lines += [
            f"{job.title} @ {job.company_name}  [score {scored_job.score}]",
            job.url,
            " · ".join(detail for detail in details if detail),
            "why: " + "; ".join(scored_job.reasons),
            "",
        ]
    return "\n".join(lines)


def render_html(intro: str, scored_jobs: list[ScoredJob]) -> str:
    blocks = [f"<p>{html.escape(intro)}</p>"]
    for scored_job in scored_jobs:
        job = scored_job.job
        details = [", ".join(job.locations[:3]) or "location not listed", describe_age(job.posted_at), f"via {job.source}"]
        blocks.append(
            "<div style='margin:0 0 18px 0;font-family:sans-serif'>"
            f"<a href='{html.escape(job.url, quote=True)}' style='font-size:16px;font-weight:600'>"
            f"{html.escape(job.title)}</a> @ <b>{html.escape(job.company_name)}</b> "
            f"<span style='color:#666'>[score {scored_job.score}]</span><br>"
            f"<span style='color:#444'>{html.escape(' · '.join(detail for detail in details if detail))}</span><br>"
            f"<span style='color:#888;font-size:12px'>{html.escape('; '.join(scored_job.reasons))}</span>"
            "</div>"
        )
    return "\n".join(blocks)


def send_email(kind: str, intro: str, scored_jobs: list[ScoredJob], dry_run: bool = False) -> None:
    """Send one email listing scored_jobs. Raises on failure so the caller can retry next run."""
    subject = build_subject(kind, scored_jobs)
    plain_text = render_plain_text(intro, scored_jobs)
    if dry_run:
        print(f"--- DRY RUN EMAIL ---\nSubject: {subject}\n\n{plain_text}")
        return

    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must be set to send email")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"Job Radar <{username}>"
    message["To"] = os.environ.get("EMAIL_TO") or username
    message.set_content(plain_text)
    message.add_alternative(render_html(intro, scored_jobs), subtype="html")

    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as connection:
            connection.login(username, password)
            connection.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as connection:
            connection.starttls()
            connection.login(username, password)
            connection.send_message(message)
