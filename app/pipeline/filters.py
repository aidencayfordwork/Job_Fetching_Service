"""The KEEP/EXCLUDE gate (architecture.md §2B/2C). Runs after Classify, so
`level` and `role_category` are already set.

Ambiguous remote/US-eligibility resolves to EXCLUDE, not include: a false
negative (missing a job) is preferable to a false positive (a job the
candidate can't actually take polluting the results).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.connectors.base import JobDraft
from app.pipeline.clearance import requires_active_clearance

_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}
_US_STATE_ABBREVS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
}

_HYBRID_ONSITE_RE = re.compile(
    r"\bhybrid\b|\bon-?site\b|\bin[\s-]office\b|\d+\s*days?\s*(?:a|per)\s*week\s*in\s*(?:the\s*)?office",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)


# "us" (lowercase, case-insensitive) collides with the ordinary English
# pronoun ("join us", "about us") constantly in JD text, so the bare
# US/USA token is matched case-SENSITIVELY (uppercase only) via the scoped
# `(?-i:...)` group, while "united states"/"u.s." stay case-insensitive
# since those multi-word/punctuated forms don't have that collision.
_US_TOKEN = r"(?-i:USA?)"

_EXCLUSION_CARVEOUT_RE = re.compile(
    rf"(excluding|except|not\s+(?:available|open|eligible)\s+(?:to|in|for)|no)\s+(?:the\s+)?(?:{_US_TOKEN}|u\.s\.|united\s+states)\b",
    re.IGNORECASE,
)
_US_SIGNAL_RE = re.compile(rf"\b(united\s+states|{_US_TOKEN}|u\.s\.)\b", re.IGNORECASE)
_WORLDWIDE_RE = re.compile(
    r"anywhere\s+in\s+the\s+world|worldwide|\bglobal(?:ly)?\b|any\s*time\s*zone", re.IGNORECASE
)
_NORTH_AMERICA_RE = re.compile(r"north(?:ern)?\s+america", re.IGNORECASE)
_NON_US_REGION_WORD_RE = re.compile(
    r"\b(uk|united\s+kingdom|eu|europe|emea|apac|latam|canada|india)\b", re.IGNORECASE
)
_NON_US_REGION_ONLY_RE = re.compile(
    r"\b(uk|united\s+kingdom|eu|europe|emea|apac|latam|canada|india)\s+only\b|only\s+(?:the\s+)?(uk|eu|europe|emea|apac|latam|canada|india)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RemoteAssessment:
    is_remote: bool | None
    us_eligible: bool | None
    remote_scope: str | None
    eligible_states: list[str]


def assess_remote_us(job: JobDraft) -> RemoteAssessment:
    location_text = job.original_location or ""
    # Only look at the first ~1500 chars of the JD - remote/location
    # requirements are stated up front; scanning the whole JD risks
    # picking up unrelated mentions (e.g. "our Austin office" deep in a
    # "who we are" section).
    jd_excerpt = (job.cleaned_job_description or "")[:1500]
    combined = f"{location_text}\n{jd_excerpt}"

    us_eligible, remote_scope, eligible_states = _assess_us_eligibility(location_text, jd_excerpt)

    is_remote = job.is_remote
    if is_remote is None:
        if _HYBRID_ONSITE_RE.search(combined):
            is_remote = False
        elif _REMOTE_RE.search(combined):
            is_remote = True
        elif _WORLDWIDE_RE.search(combined) or remote_scope in ("US", "US-partial"):
            # "Anywhere in the world" / an explicit US(-partial) location
            # scope only makes sense for a remote role, even without the
            # literal word "remote" appearing.
            is_remote = True
    elif _HYBRID_ONSITE_RE.search(combined):
        # A source-provided is_remote=True can still be contradicted by an
        # explicit hybrid/onsite mention in the JD body.
        is_remote = False

    return RemoteAssessment(
        is_remote=is_remote,
        us_eligible=us_eligible,
        remote_scope=remote_scope,
        eligible_states=eligible_states,
    )


def _assess_us_eligibility(location_text: str, jd_excerpt: str) -> tuple[bool | None, str | None, list[str]]:
    combined = f"{location_text}\n{jd_excerpt}"

    if _EXCLUSION_CARVEOUT_RE.search(combined):
        return False, None, []

    # A concrete list of US states/abbreviations is unambiguous evidence
    # of US eligibility - but only trusted from the concise location field
    # itself, not the broader JD body, which routinely mentions state/city
    # names as incidental boilerplate (e.g. "co-working offices in San
    # Francisco, New York, and London") unrelated to this job's actual
    # eligibility scope.
    states = _extract_states(location_text)
    if states:
        return True, "US-partial", states

    if _US_SIGNAL_RE.search(combined):
        return True, "US", []

    if _WORLDWIDE_RE.search(combined):
        return True, "Global", []

    if _NORTH_AMERICA_RE.search(combined):
        # Ambiguous on its own (could be Canada-only, or one region among
        # several listed alongside it) - not confident enough to include,
        # and checked before the bare-region-word rule below so a location
        # like "Northern America, LATAM, Europe, APAC" stays ambiguous
        # rather than being read as a confident non-US region.
        return None, None, []

    # The concise location field naming a single non-US region (e.g. just
    # "Europe") is confident evidence on its own, no "only" qualifier
    # needed - that field IS the stated scope. A stray region mention
    # buried in the JD body needs the stronger "<region> only" phrasing to
    # count, to avoid false positives from unrelated mentions.
    if _NON_US_REGION_WORD_RE.search(location_text) or _NON_US_REGION_ONLY_RE.search(combined):
        return False, None, []

    return None, None, []


_STATE_ABBREV_LIST_RE = re.compile(r"\b([A-Z]{2})\b(?:\s*(?:,|/|and)\s*([A-Z]{2})\b)+")


def _extract_states(text: str) -> list[str]:
    found = {name for name in _US_STATES if name in text.lower()}

    # 2-letter abbreviations collide with common English words when
    # lowercase ("in", "or", "me", "hi", "ok"...), so only trust them when
    # they appear ALL-CAPS in what looks like a delimited list (e.g.
    # "Remote (CA, NY, WA)") - real sentences don't capitalize standalone
    # words like that, but real state-code lists in job postings do.
    for match in _STATE_ABBREV_LIST_RE.finditer(text):
        for group in match.groups():
            if group and group.lower() in _US_STATE_ABBREVS:
                found.add(group.lower())

    return sorted(found)


@dataclass(frozen=True, slots=True)
class FilterOutcome:
    kept: bool
    reason: str | None
    job: JobDraft


def apply_filters(job: JobDraft) -> FilterOutcome:
    """Run the full KEEP/EXCLUDE gate. Must run after classify_level and
    classify_role. Populates job's remote/US/clearance fields regardless
    of the outcome (useful for debugging why a job was excluded)."""
    assessment = assess_remote_us(job)
    job.is_remote = assessment.is_remote
    job.us_eligible = assessment.us_eligible
    job.remote_scope = assessment.remote_scope
    job.eligible_states = assessment.eligible_states

    job.requires_active_clearance = requires_active_clearance(job.cleaned_job_description)

    if job.requires_active_clearance:
        return FilterOutcome(False, "requires_active_clearance", job)

    if job.is_remote is not True:
        return FilterOutcome(False, "not_confirmed_remote", job)

    if job.us_eligible is not True:
        return FilterOutcome(False, "not_confirmed_us_eligible", job)

    if job.role_category is None:
        return FilterOutcome(False, "not_a_target_role", job)

    if job.level is None:
        return FilterOutcome(False, "seniority_out_of_band", job)

    return FilterOutcome(True, None, job)
