"""Rebuild the platform's publish records from BidFlow's feed when they are
missing - e.g. the platform database was lost or restored from an old backup.

Without this, a lost record would make the platform insert jobs again under
new keys (a second live row for the same opening), never close rows it no
longer knows about (filled jobs stuck on BidFlow's board), and re-send
everything with a new verified_at (an alert burst). BidFlow's job_feed.jobs
is the record of what was published, and jobfeed_writer may SELECT it.

Runs at the start of every publish run; with nothing missing it costs one
key-only SELECT.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from rapidfuzz import fuzz
from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.db.models import FeedPublication, FeedPublishLog, Job, JobAltSource, Source, SourceRun
from app.pipeline.dedupe import normalize_company_name
from app.pipeline.submission import ingest_submission
from app.publish.contract import UPSERT_SQL
from app.publish.feed_row import as_utc, content_hash, row_from_feed
from app.schemas.job import JobSubmission

log = get_logger(__name__)

FUZZY_TITLE_MATCH = 90
MANUAL_SOURCES = {"linkedin"}

_WRITER_COLUMNS = (
    "source, source_job_id, job_url, jd_text, company, title, country_code, work_type, location_text, "
    "employment_type, posted_at, verified_at, salary_min, salary_max, salary_text, tags, status"
)


@dataclass
class ReconcileSummary:
    adopted: int = 0
    reimported: int = 0
    orphans_closed: int = 0
    orphans_waiting: int = 0


async def reconcile(
    session: AsyncSession, feed_engine: AsyncEngine, now: datetime, only_sources: set[str] | None = None
) -> ReconcileSummary:
    """`only_sources` limits the scan (tests); default is every source this
    platform publishes under."""
    summary = ReconcileSummary()
    publications = list((await session.execute(select(FeedPublication))).scalars())
    pinned = {(p.feed_source, p.feed_source_job_id) for p in publications}
    published_jobs = {p.job_id for p in publications}
    fetched_sources = set((await session.execute(select(Source.name))).scalars())
    sources = only_sources if only_sources is not None else (
        fetched_sources | MANUAL_SOURCES | {p.feed_source for p in publications}
    )
    if not sources:
        return summary

    async with feed_engine.connect() as conn:
        keys = (
            await conn.execute(
                text("SELECT source, source_job_id FROM job_feed.jobs WHERE source = ANY(:sources)"),
                {"sources": sorted(sources)},
            )
        ).all()
        unknown = [(k.source, k.source_job_id) for k in keys if (k.source, k.source_job_id) not in pinned]
        if not unknown:
            return summary
        records = (
            await conn.execute(
                text(
                    f"SELECT {_WRITER_COLUMNS}, created_at FROM job_feed.jobs "
                    "WHERE (source, source_job_id) IN "
                    "(SELECT * FROM unnest(CAST(:s AS text[]), CAST(:i AS text[]))) "
                    "ORDER BY created_at, source, source_job_id"
                ),
                {"s": [k[0] for k in unknown], "i": [k[1] for k in unknown]},
            )
        ).mappings().all()

    direct = {
        (r.source, r.source_job_id): r.id
        for r in (await session.execute(select(Job.id, Job.source, Job.source_job_id).where(Job.source.in_(sources)))).all()
    }
    alternates = {
        (r.source, r.source_job_id): r.job_id
        for r in (
            await session.execute(
                select(JobAltSource.job_id, JobAltSource.source, JobAltSource.source_job_id).where(
                    JobAltSource.source.in_(sources)
                )
            )
        ).all()
    }
    unpublished = [
        j for j in (await session.execute(select(Job).where(Job.active.is_(True)))).scalars()
        if j.id not in published_jobs
    ]

    orphans = []
    for record in records:
        key = (record["source"], record["source_job_id"])
        job_id = direct.get(key) or alternates.get(key)
        if job_id is None and record["status"] == "ACTIVE" and key[0] not in fetched_sources:
            # A manually submitted job can't be re-fetched; BidFlow's copy is
            # the only one left, so run it through the submission path again.
            job_id = await _reimport(session, record)
            summary.reimported += job_id is not None
        if job_id is None and record["status"] == "ACTIVE":
            job_id = _similar_unpublished_job(record, unpublished, published_jobs)
        if job_id is not None and job_id not in published_jobs:
            _adopt(session, job_id, record, now)
            published_jobs.add(job_id)
            summary.adopted += 1
        elif record["status"] == "ACTIVE":
            # No platform job, or its job is already published under another
            # key (a duplicate on BidFlow's board).
            orphans.append(record)
    await session.commit()

    if orphans:
        if await _platform_is_warm(session):
            summary.orphans_closed = await _close_orphans(session, feed_engine, orphans, now)
        else:
            # Right after a data loss the platform hasn't re-fetched yet, so an
            # unmatched row may still be a live job; wait for a full cycle.
            summary.orphans_waiting = len(orphans)

    if summary.adopted or summary.orphans_closed or summary.orphans_waiting:
        log.info("publish_records_reconciled", **vars(summary))
    return summary


def _adopt(session: AsyncSession, job_id: int, record, now: datetime) -> None:
    session.add(
        FeedPublication(
            job_id=job_id, feed_source=record["source"], feed_source_job_id=record["source_job_id"],
            # The hash of what BidFlow holds, so an unchanged job isn't re-sent.
            sent_hash=content_hash(row_from_feed(record)), last_result="ADOPTED", last_attempted_at=now,
            feed_status=record["status"], verified_at=record["verified_at"],
            first_published_at=record["created_at"],
        )
    )
    session.add(
        FeedPublishLog(
            job_id=job_id, feed_source=record["source"], feed_source_job_id=record["source_job_id"],
            result="ADOPTED", status=record["status"],
        )
    )


async def _reimport(session: AsyncSession, record) -> int | None:
    # Keep adoptions made so far out of the rollback below.
    await session.commit()
    try:
        submission = JobSubmission(
            source_url=record["job_url"], company_name=record["company"], job_title=record["title"],
            raw_job_description=record["jd_text"], source=record["source"],
            original_location=record["location_text"], posted_at=record["posted_at"],
            original_salary_text=record["salary_text"],
        )
        result = await ingest_submission(session, submission, source_job_id=record["source_job_id"])
    except Exception:
        log.warning("reconcile_reimport_failed", source=record["source"], exc_info=True)
        await session.rollback()
        return None
    return result.job_id if result.status != "rejected" else None


def _similar_unpublished_job(record, unpublished: list[Job], published_jobs: set[int]) -> int | None:
    """The same opening now stored under a different source (e.g. first seen
    on an aggregator, now found on the employer's ATS)."""
    company = normalize_company_name(record["company"])
    best, best_score = None, 0.0
    for job in unpublished:
        if job.id in published_jobs or normalize_company_name(job.company_name) != company:
            continue
        score = fuzz.token_set_ratio(record["title"], job.job_title)
        if score > best_score:
            best, best_score = job.id, score
    return best if best_score >= FUZZY_TITLE_MATCH else None


async def _platform_is_warm(session: AsyncSession) -> bool:
    """Every enabled source has finished a run since the platform's oldest
    stored job was created - so any job still live would be stored by now."""
    oldest = await session.scalar(select(func.min(Job.created_at)))
    if oldest is None:
        return False
    lacking = await session.scalar(
        select(func.count())
        .select_from(Source)
        .where(
            Source.enabled.is_(True),
            ~exists().where(
                SourceRun.source_id == Source.id,
                SourceRun.status.in_(["success", "partial"]),
                SourceRun.started_at >= oldest,
            ),
        )
    )
    return lacking == 0


async def _close_orphans(session: AsyncSession, feed_engine: AsyncEngine, orphans: list, now: datetime) -> int:
    max_age = timedelta(days=get_settings().max_job_age_days)
    closed = 0
    async with feed_engine.begin() as conn:
        for record in orphans:
            params = {k: record[k] for k in record.keys() if k != "created_at"}
            posted = as_utc(record["posted_at"])
            params["status"] = "EXPIRED" if posted is not None and posted < now - max_age else "CLOSED"
            try:
                async with conn.begin_nested():
                    await conn.execute(UPSERT_SQL, params)
            except (IntegrityError, DataError):
                log.warning("orphan_close_rejected", source=record["source"], exc_info=True)
                continue
            closed += 1
            session.add(
                FeedPublishLog(
                    job_id=None, feed_source=record["source"], feed_source_job_id=record["source_job_id"],
                    result="ORPHAN_CLOSED", status=params["status"],
                )
            )
    await session.commit()
    return closed
