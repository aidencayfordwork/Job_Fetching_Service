"""Seniority classification: MID / SENIOR / STAFF / LEAD, or None to
exclude (junior/intern/new-grad on one end, principal/director+ on the
other — per the KEEP/EXCLUDE bands in architecture.md §2B/2C).

Title keywords are checked first (strong, explicit signal) and always win
over JD-derived signals. Exclusion markers are checked before inclusion
markers so e.g. "Senior Principal Engineer" is correctly excluded rather
than classified SENIOR.
"""

from __future__ import annotations

import re

from app.connectors.base import JobDraft

_EXCLUDE_TITLE_RE = re.compile(
    r"""(?<![A-Za-z0-9])(
        intern(?:ship)? |
        new\s*grad(?:uate)? |
        entry[\s-]?level |
        jr\.? |
        junior |
        principal |
        distinguished |
        fellow |
        director |
        vp |
        vice\s+president |
        head\s+of |
        chief
    )(?![A-Za-z0-9])""",
    re.IGNORECASE | re.VERBOSE,
)

_LEAD_TITLE_RE = re.compile(r"(?<![A-Za-z0-9])(lead|tech\s+lead|team\s+lead)(?![A-Za-z0-9])", re.IGNORECASE)
_STAFF_TITLE_RE = re.compile(r"(?<![A-Za-z0-9])staff(?![A-Za-z0-9])", re.IGNORECASE)
_SENIOR_TITLE_RE = re.compile(r"(?<![A-Za-z0-9])(senior|sr\.?)(?![A-Za-z0-9])", re.IGNORECASE)
_MID_TITLE_RE = re.compile(r"(?<![A-Za-z0-9])mid[\s-]?level(?![A-Za-z0-9])", re.IGNORECASE)

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?\+?\s*years?", re.IGNORECASE)


def classify_level(job: JobDraft) -> JobDraft:
    """Set `job.level` (and `job.required_years_experience` when found in
    the JD) in place. `level` is left None when the job should be
    excluded by seniority (caller/filters.py acts on that)."""
    title = job.job_title or ""

    if _EXCLUDE_TITLE_RE.search(title):
        job.level = None
        return job

    if _LEAD_TITLE_RE.search(title):
        job.level = "LEAD"
        return job
    if _STAFF_TITLE_RE.search(title):
        job.level = "STAFF"
        return job
    if _SENIOR_TITLE_RE.search(title):
        job.level = "SENIOR"
        return job
    if _MID_TITLE_RE.search(title):
        job.level = "MID"
        return job

    # Title had no seniority marker at all - fall back to JD analysis.
    jd = job.cleaned_job_description or ""

    if _EXCLUDE_TITLE_RE.search(jd[:500]):
        # An exclusion marker near the top of the JD (e.g. "This is an
        # entry-level position") is a strong enough signal to exclude even
        # without a title marker.
        job.level = None
        return job

    years = _extract_years(jd)
    if years is not None:
        job.required_years_experience = years
        if years < 2:
            job.level = None
        elif years <= 4:
            job.level = "MID"
        elif years <= 7:
            job.level = "SENIOR"
        else:
            job.level = "STAFF"
        return job

    # No signal anywhere. An unqualified "Software Engineer" posting with
    # no explicit level and no stated years is, in practice, most often a
    # standard mid-level role - defaulting to MID here is a judgment call,
    # not an invented fact about this specific job; leaving it fully
    # unclassified would exclude a large share of legitimate postings that
    # simply don't spell out a level.
    job.level = "MID"
    return job


def _extract_years(text: str) -> int | None:
    match = _YEARS_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
