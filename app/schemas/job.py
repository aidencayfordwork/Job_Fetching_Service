from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobCard(BaseModel):
    """Compact shape for the job-list/job-card view (architecture.md §2E)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    job_title: str
    source: str
    level: str | None
    role_category: str | None
    main_stack: list[str]
    industry: str | None
    required_years_experience: int | None
    salary_min: float | None
    salary_max: float | None
    currency: str | None
    salary_period: str | None
    remote_scope: str | None
    eligible_states: list[str]
    posted_at: datetime | None
    last_seen_at: datetime
    source_url: str
    direct_apply_url: str | None


class JobDetail(JobCard):
    """Full record, including the JD, for the job-detail view."""

    source_job_id: str
    full_technology_stack: list[str]
    employment_type: str | None
    is_remote: bool | None
    us_eligible: bool | None
    excluded_states: list[str]
    timezone_requirement: str | None
    original_location: str | None
    original_salary_text: str | None
    source_updated_at: datetime | None
    first_seen_at: datetime
    cleaned_job_description: str | None
    responsibilities: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    matched_keywords: list[str]
    requires_active_clearance: bool
    active: bool
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobCard]
    total: int
    page: int
    page_size: int


class JobSubmission(BaseModel):
    """A job found manually (e.g. on LinkedIn by a human, not a scraper)
    and submitted by the Job Application Service for ingestion through
    the same pipeline - and the same exclusion rules - as fetched jobs."""

    source_url: HttpUrl
    company_name: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    raw_job_description: str = Field(min_length=1)

    # Which site this was found on - lets the same endpoint serve other
    # manually-sourced sites later without a schema change. Recorded
    # as-is in jobs.source; an unrecognized value just defaults to the
    # lowest dedup priority (see dedupe.SOURCE_PRIORITY) rather than
    # being rejected outright.
    source: str = "linkedin"

    direct_apply_url: HttpUrl | None = None
    original_location: str | None = None
    posted_at: datetime | None = None
    original_salary_text: str | None = None


class JobSubmissionResult(BaseModel):
    status: Literal["created", "updated", "duplicate", "rejected"]
    reason: str | None = None
    job_id: int | None = None
