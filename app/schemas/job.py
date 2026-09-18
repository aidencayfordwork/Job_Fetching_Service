from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
