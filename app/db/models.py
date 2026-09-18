from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # ats | aggregator_api | rss
    fetch_interval_seconds: Mapped[int] = mapped_column(nullable=False, default=10800)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    runs: Mapped[list["SourceRun"]] = relationship(back_populates="source")


class AtsCompany(Base):
    __tablename__ = "ats_companies"
    __table_args__ = (
        UniqueConstraint("ats_platform", "board_token", name="uq_ats_companies_platform_token"),
        Index("ix_ats_companies_enabled_platform", "enabled", "ats_platform"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ats_platform: Mapped[str] = mapped_column(String(32), nullable=False)  # greenhouse | lever | ashby | smartrecruiters
    board_token: Mapped[str] = mapped_column(String(255), nullable=False)
    source_of_discovery: Mapped[str] = mapped_column(String(32), nullable=False, default="organic")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (Index("ix_source_runs_source_started", "source_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    jobs_fetched: Mapped[int] = mapped_column(default=0)
    jobs_new: Mapped[int] = mapped_column(default=0)
    jobs_updated: Mapped[int] = mapped_column(default=0)
    jobs_filtered_out: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    source: Mapped["Source"] = relationship(back_populates="runs")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_source_job_id"),
        UniqueConstraint("canonical_fingerprint", name="uq_jobs_canonical_fingerprint"),
        Index("ix_jobs_active_posted_at", "active", "posted_at"),
        Index("ix_jobs_level", "level"),
        Index("ix_jobs_role_category", "role_category"),
        Index("ix_jobs_company_name", "company_name"),
        Index("ix_jobs_main_stack", "main_stack", postgresql_using="gin"),
        Index("ix_jobs_full_technology_stack", "full_technology_stack", postgresql_using="gin"),
        Index("ix_jobs_extracted_keywords", "extracted_keywords", postgresql_using="gin"),
        Index("ix_jobs_salary_range", "salary_min", "salary_max"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
        Index("ix_jobs_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Identity
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    direct_apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # MID | SENIOR | STAFF | LEAD
    role_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    main_stack: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    full_technology_stack: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    required_years_experience: Mapped[int | None] = mapped_column(nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Remote
    is_remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    us_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    remote_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)  # US | US-partial | Global | Unknown
    eligible_states: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    excluded_states: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    timezone_requirement: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Compensation
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_salary_text: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Dates
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # JD
    raw_job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    required_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    extracted_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Internal
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_active_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canonical_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)


class JobRawPayload(Base):
    __tablename__ = "job_raw_payloads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobAltSource(Base):
    __tablename__ = "job_alt_sources"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_job_alt_sources_source_source_job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
