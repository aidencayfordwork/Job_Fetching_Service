"""Idempotent persistence: where a JobDraft becomes (or updates) a `jobs`
row. Three-way identity resolution per job:

1. Same (source, source_job_id) already in the DB -> refresh that exact
   row in place (the common "re-fetched, maybe slightly updated" case).
2. Not found by (1), but a fuzzy/fingerprint match against another
   source's recent job -> this is the same real-world job seen on a new
   source. Record it in job_alt_sources; promote it to canonical only if
   it outranks the current canonical source (architecture.md §5.3).
3. Neither -> genuinely new job -> insert a new `jobs` row.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.ats_common import AtsTarget
from app.connectors.base import JobDraft
from app.core.logging import get_logger
from app.db.models import AtsCompany, Job, JobAltSource, Source, SourceRun
from app.pipeline.dedupe import ExistingJobRef, find_duplicate, is_higher_priority_source

log = get_logger(__name__)

JOB_EVENTS_CHANNEL = "job_events"


async def _notify_job_event(session: AsyncSession, event: str, row: Job) -> None:
    """NOTIFY on JOB_EVENTS_CHANNEL for the /stream SSE endpoint
    (architecture.md §9). Postgres defers delivery until the transaction
    commits, so this is safe to call before the caller's final commit()."""
    payload = json.dumps(
        {
            "event": event,
            "job_id": row.id,
            "source": row.source,
            "company_name": row.company_name,
            "job_title": row.job_title,
        }
    )
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": JOB_EVENTS_CHANNEL, "payload": payload})

# JobDraft field names that map 1:1 onto Job columns of the same name.
_DIRECT_FIELDS = [
    f.name
    for f in fields(JobDraft)
    if f.name not in {"raw_payload"}
]


def _apply_draft_to_row(row: Job, job: JobDraft, now: datetime) -> None:
    for name in _DIRECT_FIELDS:
        setattr(row, name, getattr(job, name))
    row.last_seen_at = now
    row.active = True
    row.updated_at = now


async def get_recent_active_jobs(session: AsyncSession, days: int = 30) -> list[ExistingJobRef]:
    """Cross-source dedup candidate pool: all active jobs first seen in
    the last `days`. Cheap full scan at this scale (a few thousand rows at
    most) - normalizing company names in Python (dedupe.py) rather than
    pushing that logic into SQL keeps this simple."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = select(Job).where(Job.active.is_(True), Job.first_seen_at >= cutoff)
    result = await session.execute(stmt)
    return [
        ExistingJobRef(
            id=row.id,
            source=row.source,
            source_job_id=row.source_job_id,
            company_name=row.company_name,
            job_title=row.job_title,
            canonical_fingerprint=row.canonical_fingerprint,
        )
        for row in result.scalars()
    ]


async def upsert_job(
    session: AsyncSession, job: JobDraft, dedupe_candidates: list[ExistingJobRef]
) -> tuple[Job, bool]:
    """Persist one kept JobDraft. Returns (row, is_new)."""
    now = datetime.now(UTC)

    existing_same_source = await session.scalar(
        select(Job).where(Job.source == job.source, Job.source_job_id == job.source_job_id)
    )
    if existing_same_source is not None:
        _apply_draft_to_row(existing_same_source, job, now)
        await _notify_job_event(session, "job.updated", existing_same_source)
        return existing_same_source, False

    duplicate = find_duplicate(job, dedupe_candidates)
    if duplicate is not None:
        canonical_row = await session.get(Job, duplicate.id)
        assert canonical_row is not None

        if is_higher_priority_source(job.source, canonical_row.source):
            # This new source outranks the current canonical one (e.g. we
            # just found the employer's own Greenhouse posting for a job
            # we previously only had via an aggregator) - promote it, and
            # record the previously-canonical source as an alt source.
            old_source = canonical_row.source
            old_source_job_id = canonical_row.source_job_id
            old_source_url = canonical_row.source_url
            _apply_draft_to_row(canonical_row, job, now)
            await _record_alt_source_raw(
                session, canonical_row.id, old_source, old_source_job_id, old_source_url, now
            )
        else:
            # Existing stays canonical; record this sighting as an alt source.
            await _record_alt_source(session, canonical_row.id, job, now)
            canonical_row.last_seen_at = now
            canonical_row.active = True

        await _notify_job_event(session, "job.updated", canonical_row)
        return canonical_row, False

    new_row = Job(**{name: getattr(job, name) for name in _DIRECT_FIELDS})
    new_row.first_seen_at = now
    new_row.last_seen_at = now
    new_row.active = True
    session.add(new_row)
    await session.flush()
    await _notify_job_event(session, "job.created", new_row)
    return new_row, True


async def _record_alt_source(session: AsyncSession, job_id: int, job: JobDraft, now: datetime) -> None:
    await _record_alt_source_raw(session, job_id, job.source, job.source_job_id, job.source_url, now)


async def _record_alt_source_raw(
    session: AsyncSession, job_id: int, source: str, source_job_id: str, source_url: str, now: datetime
) -> None:
    existing = await session.scalar(
        select(JobAltSource).where(
            JobAltSource.source == source, JobAltSource.source_job_id == source_job_id
        )
    )
    if existing is not None:
        return
    session.add(
        JobAltSource(
            job_id=job_id, source=source, source_job_id=source_job_id,
            source_url=source_url, first_seen_at=now,
        )
    )


async def mark_expired_jobs(session: AsyncSession, grace_days: int = 5) -> int:
    """Jobs not re-seen within the grace window get marked inactive
    rather than deleted (architecture.md §3: keep historical jobs)."""
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    stmt = (
        update(Job)
        .where(Job.active.is_(True), Job.last_seen_at < cutoff)
        .values(active=False, updated_at=datetime.now(UTC))
        .returning(Job)
    )
    result = await session.execute(stmt)
    deactivated = list(result.scalars())
    for row in deactivated:
        await _notify_job_event(session, "job.deactivated", row)
    return len(deactivated)


async def get_enabled_ats_companies(session: AsyncSession, ats_platform: str) -> list[AtsTarget]:
    stmt = select(AtsCompany).where(
        AtsCompany.ats_platform == ats_platform, AtsCompany.enabled.is_(True)
    )
    result = await session.execute(stmt)
    return [AtsTarget(company_name=row.company_name, board_token=row.board_token) for row in result.scalars()]


async def get_source_by_name(session: AsyncSession, name: str) -> Source | None:
    return await session.scalar(select(Source).where(Source.name == name))


async def get_last_successful_fetch_time(session: AsyncSession, source_id: int) -> datetime | None:
    stmt = (
        select(SourceRun.finished_at)
        .where(SourceRun.source_id == source_id, SourceRun.status.in_(["success", "partial"]))
        .order_by(SourceRun.finished_at.desc(), SourceRun.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def start_source_run(session: AsyncSession, source_id: int) -> SourceRun:
    run = SourceRun(source_id=source_id, status="running")
    session.add(run)
    await session.flush()
    return run


async def finish_source_run(
    session: AsyncSession,
    run: SourceRun,
    *,
    status: str,
    jobs_fetched: int,
    jobs_new: int,
    jobs_updated: int,
    jobs_filtered_out: int,
    error_message: str | None = None,
) -> None:
    finished_at = datetime.now(UTC)
    run.finished_at = finished_at
    run.status = status
    run.jobs_fetched = jobs_fetched
    run.jobs_new = jobs_new
    run.jobs_updated = jobs_updated
    run.jobs_filtered_out = jobs_filtered_out
    run.error_message = error_message
    if run.started_at is not None:
        run.duration_ms = int((finished_at - run.started_at).total_seconds() * 1000)
