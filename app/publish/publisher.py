"""Publish verified US-remote jobs into BidFlow's job_feed.jobs
(docs/bidflow/JOB_FEED_CONTRACT.md).

Per run: read BidFlow's tag catalog, work out each job's feed row, send only
rows whose content changed since the last attempt, in batches with one
savepoint per row so a rejected row is logged and skipped instead of rolling
back the batch. Jobs that went inactive (or stopped verifying) are sent as
CLOSED/EXPIRED; nothing is ever deleted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from app.config import get_settings
from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.db.models import FeedPublication, FeedPublishLog, Job
from app.publish.catalog import TagCatalog, load_catalog
from app.publish.feed_row import build_row, content_hash, feed_status, hold_back_reason, jd_text
from app.publish.tagging import choose_tags

log = get_logger(__name__)

BATCH_SIZE = 200
VERIFIED_AT_REFRESH = timedelta(days=1)

# The contract's upsert, verbatim, plus a RETURNING clause to tell
# inserted / updated / unchanged apart (updated_at only moves when a value
# really changed, and now() is the transaction's timestamp).
UPSERT_SQL = text("""
INSERT INTO job_feed.jobs (
    source, source_job_id, job_url, jd_text, company, title,
    country_code, work_type, location_text, employment_type,
    posted_at, verified_at, salary_min, salary_max, salary_text,
    tags, status
) VALUES (
    :source, :source_job_id, :job_url, :jd_text, :company, :title,
    :country_code, :work_type, :location_text, :employment_type,
    :posted_at, :verified_at, :salary_min, :salary_max, :salary_text,
    :tags, :status
)
ON CONFLICT (source, source_job_id) DO UPDATE SET
    job_url = EXCLUDED.job_url, jd_text = EXCLUDED.jd_text, company = EXCLUDED.company,
    title = EXCLUDED.title, location_text = EXCLUDED.location_text,
    employment_type = EXCLUDED.employment_type, posted_at = EXCLUDED.posted_at,
    verified_at = EXCLUDED.verified_at, salary_min = EXCLUDED.salary_min,
    salary_max = EXCLUDED.salary_max, salary_text = EXCLUDED.salary_text,
    tags = EXCLUDED.tags, status = EXCLUDED.status
RETURNING (xmax = 0) AS inserted, (updated_at = now()) AS touched
""")

_AUTH_SQLSTATES = {"28000", "28P01"}


class FeedAuthError(RuntimeError):
    """BidFlow rejected the credentials - its admin rotated the password."""


@dataclass
class PlannedRow:
    job_id: int
    feed_source: str
    feed_source_job_id: str
    row: dict
    sent_hash: str


@dataclass
class PublishSummary:
    results: Counter = field(default_factory=Counter)
    held_back: Counter = field(default_factory=Counter)
    skipped_unchanged: int = 0


_feed_engine: AsyncEngine | None = None


def get_feed_engine() -> AsyncEngine | None:
    global _feed_engine
    settings = get_settings()
    if not settings.bidflow_database_url:
        return None
    if _feed_engine is None:
        connect_args = {} if settings.bidflow_ssl == "disable" else {"ssl": settings.bidflow_ssl}
        _feed_engine = create_async_engine(
            settings.bidflow_database_url, pool_size=2, max_overflow=1, pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _feed_engine


async def run_publish(
    session: AsyncSession | None = None,
    feed_engine: AsyncEngine | None = None,
    job_ids: list[int] | None = None,
) -> PublishSummary:
    """`job_ids` limits the run to those jobs (tests); default is every job."""
    feed_engine = feed_engine or get_feed_engine()
    if feed_engine is None:
        log.info("publish_skipped_not_configured")
        return PublishSummary()
    if session is not None:
        return await _run(session, feed_engine, job_ids)
    async with async_session_factory() as owned:
        return await _run(owned, feed_engine, job_ids)


async def _run(session: AsyncSession, feed_engine: AsyncEngine, job_ids: list[int] | None) -> PublishSummary:
    summary = PublishSummary()
    now = datetime.now(UTC)
    try:
        async with feed_engine.connect() as conn:
            catalog = await load_catalog(conn)
    except Exception as exc:
        _raise_if_auth_error(exc)
        raise

    publications = {p.job_id: p for p in (await session.execute(select(FeedPublication))).scalars()}
    pinned = {(p.feed_source, p.feed_source_job_id): p.job_id for p in publications.values()}

    stmt = select(Job).where(or_(Job.active.is_(True), Job.id.in_(list(publications) or [-1])))
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(job_ids))
    jobs = (await session.execute(stmt.order_by(Job.id))).scalars().all()

    batch: list[PlannedRow] = []
    for job in jobs:
        planned = _plan(job, publications.get(job.id), pinned, catalog, now, summary)
        if planned is None:
            continue
        pinned[(planned.feed_source, planned.feed_source_job_id)] = job.id
        batch.append(planned)
        if len(batch) >= BATCH_SIZE:
            await _send_batch(session, feed_engine, batch, publications, now, summary)
            batch = []
    if batch:
        await _send_batch(session, feed_engine, batch, publications, now, summary)

    log.info(
        "publish_run_complete",
        results=dict(summary.results), held_back=dict(summary.held_back),
        skipped_unchanged=summary.skipped_unchanged,
    )
    return summary


def _plan(
    job: Job,
    pub: FeedPublication | None,
    pinned: dict[tuple[str, str], int],
    catalog: TagCatalog,
    now: datetime,
    summary: PublishSummary,
) -> PlannedRow | None:
    text_ = jd_text(job)
    status = feed_status(job, get_settings().max_job_age_days, now)
    reason = hold_back_reason(job, text_) if status == "ACTIVE" else None

    if pub is None or pub.feed_status is None:
        if status != "ACTIVE":
            return None  # never accepted by BidFlow, so nothing to close
        if reason:
            summary.held_back[reason] += 1
            return None
    elif reason:
        # Published earlier but no longer passes (e.g. verification rules got
        # stricter): take it off BidFlow's board rather than leave it live.
        status = "CLOSED"

    if pub is None:
        key = (job.source, job.source_job_id)
        if key in pinned and pinned[key] != job.id:
            summary.held_back["duplicate_of_published_job"] += 1
            return None
    else:
        key = (pub.feed_source, pub.feed_source_job_id)

    tags = choose_tags(job.job_title, job.role_category, text_, catalog).all
    row = build_row(job, text_, tags, status)
    sent_hash = content_hash(row)
    if pub is not None and pub.sent_hash == sent_hash:
        summary.skipped_unchanged += 1
        return None

    row.update(source=key[0], source_job_id=key[1])
    row["verified_at"] = (
        pub.verified_at
        if pub is not None and pub.verified_at is not None and now - pub.verified_at < VERIFIED_AT_REFRESH
        else now
    )
    return PlannedRow(job.id, key[0], key[1], row, sent_hash)


async def _send_batch(
    session: AsyncSession,
    feed_engine: AsyncEngine,
    batch: list[PlannedRow],
    publications: dict[int, FeedPublication],
    now: datetime,
    summary: PublishSummary,
) -> None:
    outcomes: list[tuple[PlannedRow, str, str | None, str | None]] = []
    try:
        async with feed_engine.begin() as conn:
            for planned in batch:
                outcomes.append((planned, *await _upsert_one(conn, planned)))
    except Exception as exc:
        _raise_if_auth_error(exc)
        raise

    for planned, result, constraint, message in outcomes:
        summary.results[result] += 1
        accepted = result != "REJECTED"
        pub = publications.get(planned.job_id)
        if pub is None:
            pub = FeedPublication(
                job_id=planned.job_id, feed_source=planned.feed_source,
                feed_source_job_id=planned.feed_source_job_id,
            )
            session.add(pub)
            publications[planned.job_id] = pub
        pub.sent_hash = planned.sent_hash
        pub.last_result = result
        pub.last_error = message
        pub.last_attempted_at = now
        if accepted:
            pub.feed_status = planned.row["status"]
            pub.verified_at = planned.row["verified_at"]
            pub.first_published_at = pub.first_published_at or now
        session.add(
            FeedPublishLog(
                job_id=planned.job_id, result=result, status=planned.row["status"],
                constraint_name=constraint, message=message,
            )
        )
        if not accepted:
            log.warning("publish_row_rejected", job_id=planned.job_id, constraint=constraint, error=message)
    await session.commit()


async def _upsert_one(conn: AsyncConnection, planned: PlannedRow) -> tuple[str, str | None, str | None]:
    try:
        async with conn.begin_nested():
            outcome = (await conn.execute(UPSERT_SQL, planned.row)).one()
    except (IntegrityError, DataError) as exc:
        cause = exc.orig.__cause__ if exc.orig is not None else None
        return "REJECTED", getattr(cause, "constraint_name", None), str(cause or exc.orig)[:1000]
    if outcome.inserted:
        return "INSERTED", None, None
    return ("UPDATED" if outcome.touched else "UNCHANGED"), None, None


def _raise_if_auth_error(exc: Exception) -> None:
    # asyncpg raises its own error on connect; inside SQLAlchemy calls it's
    # wrapped as DBAPIError -> adapter error -> asyncpg error.
    orig = getattr(exc, "orig", None)
    for candidate in (exc, orig, getattr(orig, "__cause__", None)):
        if getattr(candidate, "sqlstate", None) in _AUTH_SQLSTATES:
            log.error("bidflow_auth_failed", hint="BidFlow rotated the jobfeed_writer password; ask its admin")
            raise FeedAuthError(str(candidate)) from exc
