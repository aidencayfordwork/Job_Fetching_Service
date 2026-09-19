"""Map one of my jobs onto BidFlow's job_feed.jobs writer columns
(docs/bidflow/JOB_FEED_CONTRACT.md), and decide which jobs must not be
published at all."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.connectors.base import JobDraft
from app.db.models import Job
from app.pipeline.filters import assess_remote_us
from app.pipeline.normalize import clean_html

# These APIs only return a snippet of the description (Adzuna cuts at 500
# characters, Jooble ~300); BidFlow's resume AI needs the full text.
SNIPPET_ONLY_SOURCES = {"adzuna", "jooble"}
MIN_DESCRIPTION_CHARS = 400

_TRACKING_PARAMS = {"ref", "ref_src", "referrer", "gh_src", "source", "src", "lever-source", "lever-origin"}
_TEMPLATE_MARKERS_RE = re.compile(
    r"begin each bullet with|select one option below|\[candidates must meet|lorem ipsum", re.IGNORECASE
)
_NO_EMPLOYER_RE = re.compile(r"^\s*(?:confidential|undisclosed|stealth(?: startup)?|n/?a)\s*$", re.IGNORECASE)
_CLEARANCE_TITLE_RE = re.compile(r"clearance|\bts/sci\b|\bpolygraph\b", re.IGNORECASE)

_REMOTE_WORDS = r"(?:(?:us|usa|u\.s\.?|united\s+states)[\s,/-]+)?(?:fully\s+)?remote(?:[\s,/-]*(?:us|usa|u\.s\.?|united\s+states|us\s+only|us\s+based|north\s+america|americas|anywhere))*"
_TITLE_NOISE_RES = [
    re.compile(rf"\s*[\(\[]\s*{_REMOTE_WORDS}\s*[\)\]]\s*$", re.IGNORECASE),
    re.compile(rf"\s*[-–—|,:]\s*{_REMOTE_WORDS}\s*$", re.IGNORECASE),
    re.compile(r"\s*[\(\[]\s*(?:us|usa|u\.s\.?|united\s+states)\s*[\)\]]\s*$", re.IGNORECASE),
    re.compile(r"\s*[\(\[]\s*(?:req(?:uisition)?|r|jr|job(?:\s+id)?)?[\s#:-]*\d{3,}\s*[\)\]]\s*$", re.IGNORECASE),
    re.compile(r"\s*[\U0001F300-\U0001FAFF☀-➿]+\s*$"),
]
_EMPLOYMENT_TYPES = {
    "full_time": "FULL_TIME", "fulltime": "FULL_TIME", "full-time": "FULL_TIME",
    "part_time": "PART_TIME", "part-time": "PART_TIME", "contract": "CONTRACT",
    "contractor": "CONTRACT", "contract_to_hire": "CONTRACT_TO_HIRE",
    "internship": "INTERNSHIP", "temporary": "TEMPORARY",
}
_ANNUAL_PERIODS = {"year", "yearly", "annual", "annum"}
_SCOPE_LOCATION_TEXT = {"US": "Remote (US)", "Global": "Remote (worldwide)", "US-partial": "Remote (US, some states)"}


def jd_text(job: Job) -> str:
    return clean_html(job.raw_job_description) or (job.cleaned_job_description or "")


def hold_back_reason(job: Job, text: str) -> str | None:
    """Why this job must not be published, or None if it can be."""
    if job.source in SNIPPET_ONLY_SOURCES:
        return "description_truncated"
    if len(text) < MIN_DESCRIPTION_CHARS:
        return "description_too_short"
    if _TEMPLATE_MARKERS_RE.search(text) or _has_repeated_bullets(text):
        return "template_posting"
    if not job.company_name.strip() or _NO_EMPLOYER_RE.match(job.company_name):
        return "no_named_employer"
    if job.requires_active_clearance or _CLEARANCE_TITLE_RE.search(job.job_title):
        return "requires_clearance"
    if not job_url(job):
        return "no_http_url"
    # Re-verified here with the current rules, not trusted from when the job
    # was first stored - verification rules have been tightened since.
    draft = JobDraft(
        source=job.source, source_job_id=job.source_job_id, company_name=job.company_name,
        job_title=job.job_title, source_url=job.source_url, original_location=job.original_location,
        is_remote=job.is_remote, cleaned_job_description=text,
    )
    assessment = assess_remote_us(draft)
    if assessment.is_remote is not True or assessment.us_eligible is not True:
        return "not_verified_us_remote"
    return None


def _has_repeated_bullets(text: str) -> bool:
    bullets = Counter(line.strip() for line in text.split("\n") if line.strip().startswith("- "))
    return any(count >= 3 for count in bullets.values())


def clean_title(title: str) -> str:
    cleaned = title.strip()
    changed = True
    while changed:
        changed = False
        for pattern in _TITLE_NOISE_RES:
            new = pattern.sub("", cleaned).strip()
            if new and new != cleaned:
                cleaned, changed = new, True
    return cleaned


def canonical_url(url: str | None) -> str | None:
    if not url or not re.match(r"^https?://\S+$", url.strip(), re.IGNORECASE):
        return None
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit(("https", parts.netloc, parts.path, urlencode(query), ""))


def job_url(job: Job) -> str | None:
    # Ashby's direct_apply_url is the application form; the posting itself is
    # the better landing page for a bidder.
    return canonical_url(job.source_url) or canonical_url(job.direct_apply_url)


def annual_usd_salary(job: Job) -> tuple[float | None, float | None]:
    if (job.currency or "").upper() != "USD":
        return None, None
    period = (job.salary_period or "").lower()
    low, high = job.salary_min, job.salary_max
    low = float(low) if low is not None else None
    high = float(high) if high is not None else None
    if low is None and high is None:
        return None, None
    low, high = (low if low is not None else high), (high if high is not None else low)
    # An unstated period is accepted only when the figures can only be annual.
    if period not in _ANNUAL_PERIODS and not (period == "" and low >= 20_000):
        return None, None
    if low < 10_000 or low > high:
        return None, None
    return low, high


def feed_status(job: Job, max_age_days: int, now: datetime) -> str:
    if job.active:
        return "ACTIVE"
    posted = job.posted_at
    if posted is not None and posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    if posted is not None and posted < now - timedelta(days=max_age_days):
        return "EXPIRED"
    return "CLOSED"


def build_row(job: Job, text: str, tags: list[str], status: str) -> dict:
    """Writer columns except source/source_job_id/verified_at, which the
    publisher adds (the key is pinned per job, verified_at is refreshed on
    its own schedule)."""
    low, high = annual_usd_salary(job)
    return {
        "job_url": job_url(job),
        "jd_text": text,
        "company": job.company_name.strip(),
        "title": clean_title(job.job_title),
        "country_code": "US",
        "work_type": "REMOTE",
        "location_text": (job.original_location or "").strip() or _SCOPE_LOCATION_TEXT.get(job.remote_scope or ""),
        "employment_type": _EMPLOYMENT_TYPES.get((job.employment_type or "").lower()),
        "posted_at": job.posted_at,
        "salary_min": low,
        "salary_max": high,
        "salary_text": job.original_salary_text,
        "tags": tags,
        "status": status,
    }


def content_hash(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
