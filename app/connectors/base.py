"""Common interface every job source implements.

Each connector is fully independent: a failure or schema change in one must
never affect another. The scheduler wraps `fetch()` calls per source in
isolation with its own retry/circuit-breaker, so nothing here needs to
account for other sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SourceKind = Literal["ats", "aggregator_api", "rss"]

RawJob = dict[str, Any]


@dataclass(slots=True)
class JobDraft:
    """Canonical, connector-agnostic shape a normalizer produces from a RawJob.

    Superset of the `jobs` table columns. Only identity fields are required;
    everything else starts unknown and gets filled in by later pipeline
    stages (filter / classify / match_keywords / dedupe). Never invent a
    value here that the source didn't actually provide — leave it at the
    default (None / empty list) instead.
    """

    # Identity (required)
    source: str
    source_job_id: str
    company_name: str
    job_title: str
    source_url: str

    direct_apply_url: str | None = None

    # Classification
    level: str | None = None
    role_category: str | None = None
    main_stack: list[str] = field(default_factory=list)
    full_technology_stack: list[str] = field(default_factory=list)
    required_years_experience: int | None = None
    employment_type: str | None = None
    industry: str | None = None

    # Remote
    is_remote: bool | None = None
    us_eligible: bool | None = None
    remote_scope: str | None = None
    eligible_states: list[str] = field(default_factory=list)
    excluded_states: list[str] = field(default_factory=list)
    timezone_requirement: str | None = None
    original_location: str | None = None

    # Compensation
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    salary_period: str | None = None
    original_salary_text: str | None = None

    # Dates
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None

    # JD
    raw_job_description: str | None = None
    cleaned_job_description: str | None = None
    responsibilities: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    # Internal
    requires_active_clearance: bool = False
    canonical_fingerprint: str | None = None

    # Kept verbatim so the job can be reprocessed later without refetching.
    raw_payload: RawJob = field(default_factory=dict)


class SourceConnector(ABC):
    name: str
    kind: SourceKind

    @abstractmethod
    def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        """Yield raw records from the source.

        Use `since` for incremental fetching wherever the source API
        supports a date/updated filter; otherwise fetch the full current
        listing (pipeline dedup/upsert makes re-fetching unchanged jobs a
        cheap no-op).
        """
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: RawJob) -> JobDraft:
        """Map a single raw record to the canonical JobDraft shape."""
        raise NotImplementedError
