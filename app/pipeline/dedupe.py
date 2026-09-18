"""Cross-source deduplication (architecture.md §7).

Kept DB-agnostic and pure: `find_duplicate` takes a plain sequence of
`ExistingJobRef` (whatever persistence.repository queries out of the
`jobs` table) rather than talking to the database itself, so it's
testable without one. The persistence layer is responsible for querying
recent same-company candidates and applying the merge decision.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.connectors.base import JobDraft

_COMPANY_SUFFIXES = {"inc", "llc", "corp", "corporation", "co", "ltd", "limited", "plc"}
_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")

_FUZZY_TITLE_THRESHOLD = 90.0

# Higher wins when the same job is found on more than one source (§5.3):
# the employer's own ATS posting is preferred over an aggregator listing
# or a manually-submitted link (POST /jobs/submit) - neither of those is
# the original posting. An unrecognized source name defaults to 0 (via
# .get() in is_higher_priority_source below), which is conservative: it
# never outranks anything, so a typo'd or new source name can't
# accidentally clobber a better-sourced canonical row.
SOURCE_PRIORITY: dict[str, int] = {
    "greenhouse": 10,
    "lever": 10,
    "ashby": 10,
    "smartrecruiters": 10,
    "remoteok": 1,
    "himalayas": 1,
    "jobicy": 1,
    "weworkremotely": 1,
    "remotive": 1,
    "adzuna": 1,
    "jooble": 1,
    "linkedin": 1,
}


def normalize_company_name(name: str) -> str:
    lowered = _PUNCTUATION_RE.sub(" ", name.lower())
    words = _WHITESPACE_RE.sub(" ", lowered).strip().split(" ")
    while words and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_title(title: str) -> str:
    return _WHITESPACE_RE.sub(" ", title.strip().lower())


def compute_fingerprint(job: JobDraft) -> str:
    company = normalize_company_name(job.company_name)
    title = normalize_title(job.job_title)
    location = job.remote_scope or "unknown"
    raw = f"{company}|{title}|{location}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def is_higher_priority_source(candidate_source: str, incumbent_source: str) -> bool:
    """True if `candidate_source` should replace `incumbent_source` as the
    canonical source for the same job."""
    return SOURCE_PRIORITY.get(candidate_source, 0) > SOURCE_PRIORITY.get(incumbent_source, 0)


@dataclass(frozen=True, slots=True)
class ExistingJobRef:
    """The minimal shape persistence.repository needs to provide about an
    already-stored job for dedup comparison."""

    id: int
    source: str
    source_job_id: str
    company_name: str
    job_title: str
    canonical_fingerprint: str


def find_duplicate(job: JobDraft, candidates: list[ExistingJobRef]) -> ExistingJobRef | None:
    """Return the existing job this `job` is a duplicate of, or None if
    it looks new. `candidates` should already be scoped to a reasonable
    window (e.g. same/similar company, last ~30 days) by the caller -
    this function doesn't do that filtering itself."""
    if not candidates:
        return None

    fingerprint = compute_fingerprint(job)
    for candidate in candidates:
        if candidate.canonical_fingerprint == fingerprint:
            return candidate

    normalized_company = normalize_company_name(job.company_name)
    same_company = [c for c in candidates if normalize_company_name(c.company_name) == normalized_company]
    if not same_company:
        return None

    best: ExistingJobRef | None = None
    best_score = 0.0
    for candidate in same_company:
        score = fuzz.token_set_ratio(job.job_title, candidate.job_title)
        if score > best_score:
            best_score = score
            best = candidate

    if best is not None and best_score >= _FUZZY_TITLE_THRESHOLD:
        return best
    return None
