from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceHealthOut(BaseModel):
    source: str
    enabled: bool
    last_fetch_at: datetime | None
    last_successful_fetch_at: datetime | None
    last_status: str | None
    consecutive_failures: int
    jobs_fetched_last_run: int
    jobs_new_last_run: int
    jobs_updated_last_run: int
    errors_last_run: str | None


class SourceRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    jobs_filtered_out: int
    error_message: str | None
    duration_ms: int | None


class AtsCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    ats_platform: str
    board_token: str
    source_of_discovery: str
    verified: bool
    enabled: bool
    discovered_at: datetime
    last_verified_at: datetime | None


class StatsOut(BaseModel):
    total_active_jobs: int
    jobs_added_today: int
    jobs_added_last_24h: int
    last_fetch_at: datetime | None
