"""Fetch -> pipeline -> persist for ONE source.

Isolation is the whole point of this module: a bad company board, a
malformed job, or a mid-run network blip must never take down the whole
run or affect any other source.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.ats_common import AtsMultiCompanyConnector
from app.connectors.base import JobDraft, SourceConnector
from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.persistence import repository
from app.pipeline.dedupe import ExistingJobRef
from app.pipeline.pipeline import process_job

log = get_logger(__name__)

# An ATS job is closed after this many consecutive complete fetches of its
# board that no longer list it (boards are re-fetched every run, ~3 h).
ATS_MISSES_TO_CLOSE = 2


@dataclass
class _Seen:
    job_ids: set[str] = field(default_factory=set)
    # Boards with a job that couldn't be parsed: we can't tell what they list.
    unreadable_boards: set[str] = field(default_factory=set)


async def run_source(connector: SourceConnector, session: AsyncSession | None = None) -> None:
    """`session`: pass one in to reuse it for everything (mainly for
    tests, so they stay inside their rollback-based isolation). In
    production, per-job work gets its own fresh session instead of
    sharing one across the whole run - see `_process_one` for why."""
    if session is not None:
        await _run_source(connector, session, per_job_session=session)
        return

    async with async_session_factory() as owned_session:
        await _run_source(connector, owned_session, per_job_session=None)


async def _run_source(
    connector: SourceConnector, session: AsyncSession, per_job_session: AsyncSession | None
) -> None:
    source_row = await repository.get_source_by_name(session, connector.name)
    if source_row is None:
        log.warning("unknown_source", source=connector.name)
        return
    if not source_row.enabled:
        return

    run = await repository.start_source_run(session, source_row.id)
    await session.commit()

    since = await repository.get_last_successful_fetch_time(session, source_row.id)

    if isinstance(connector, AtsMultiCompanyConnector):
        connector.board_targets = await repository.get_enabled_ats_companies(session, connector.name)
        # A single source-wide watermark is wrong here: the company set
        # keeps growing via discovery, and a newly added company's open
        # jobs all predate the watermark, so they'd be skipped forever
        # (a run that fetched zero companies also advances it). Boards are
        # one cheap request each and upserts are idempotent, so fetch fully.
        since = None

    dedupe_candidates = await repository.get_recent_active_jobs(session)

    jobs_fetched = jobs_new = jobs_updated = jobs_filtered_out = 0
    fetch_level_error: str | None = None
    seen = _Seen()

    try:
        async for raw in connector.fetch(since):
            jobs_fetched += 1
            outcome = await _process_one(connector, raw, dedupe_candidates, per_job_session, seen)
            # Parsing/filtering is CPU work with no await for filtered-out jobs;
            # yield so the API (health checks, /jobs/submit) stays responsive.
            await asyncio.sleep(0)
            if outcome == "new":
                jobs_new += 1
            elif outcome == "updated":
                jobs_updated += 1
            else:
                jobs_filtered_out += 1
    except Exception as exc:
        fetch_level_error = str(exc)[:2000]
        log.error("source_fetch_failed", source=connector.name, error=fetch_level_error, exc_info=True)

    if fetch_level_error is None:
        status = "success"
    elif jobs_new or jobs_updated:
        status = "partial"
    else:
        status = "failed"

    await repository.finish_source_run(
        session, run, status=status, jobs_fetched=jobs_fetched, jobs_new=jobs_new,
        jobs_updated=jobs_updated, jobs_filtered_out=jobs_filtered_out,
        error_message=fetch_level_error,
    )
    await session.commit()

    if isinstance(connector, AtsMultiCompanyConnector) and fetch_level_error is None:
        boards = connector.completed_board_tokens - seen.unreadable_boards
        closed = await repository.record_ats_misses(
            session, connector.name, boards, seen.job_ids, ATS_MISSES_TO_CLOSE
        )
        await session.commit()
        if closed:
            log.info("jobs_closed_missing_from_board", source=connector.name, count=closed)

    expired = await repository.mark_expired_jobs(session)
    stale = await repository.deactivate_stale_by_posted_age(session, get_settings().max_job_age_days)
    await session.commit()
    if expired:
        log.info("jobs_marked_inactive", source=connector.name, count=expired)
    if stale:
        log.info("jobs_marked_inactive_by_age", source=connector.name, count=stale)


async def _process_one(
    connector: SourceConnector,
    raw: dict,
    dedupe_candidates: list[ExistingJobRef],
    per_job_session: AsyncSession | None,
    seen: _Seen,
) -> str:
    """Returns 'new' / 'updated' / 'filtered'. Never raises - a single bad
    job must not abort the rest of the run.

    Uses its own fresh, short-lived session per job in production
    (`per_job_session` is None) rather than sharing one long-lived session
    across an entire run. A run can mean hundreds of sequential commits
    (e.g. Himalayas, which can yield ~1000 jobs in one fetch) - sharing
    one session that long triggered a real "MissingGreenlet" crash from
    accumulated SQLAlchemy session state, seen live. `per_job_session`,
    when given (tests), is reused instead so the caller's transaction-
    rollback isolation still covers everything.
    """
    board = raw.get("_board_token")
    try:
        draft = connector.normalize(raw)
        draft.ats_board_token = board
        seen.job_ids.add(draft.source_job_id)
        result = process_job(draft, dedupe_candidates)
    except Exception:
        # Unparseable: we can't tell whether this board still lists its jobs.
        if board:
            seen.unreadable_boards.add(board)
        log.warning("job_processing_failed", source=connector.name, raw_keys=list(raw.keys()), exc_info=True)
        return "filtered"

    if not result.kept:
        return "filtered"

    try:
        if per_job_session is not None:
            row, is_new = await _upsert(per_job_session, result.job, dedupe_candidates)
        else:
            async with async_session_factory() as session:
                row, is_new = await _upsert(session, result.job, dedupe_candidates)
    except Exception:
        log.warning("job_processing_failed", source=connector.name, raw_keys=list(raw.keys()), exc_info=True)
        if per_job_session is not None:
            try:
                await per_job_session.rollback()
            except Exception:
                # The rollback itself failing (e.g. connection already
                # broken) must not escape either - that would defeat the
                # whole point of this being a per-job isolation boundary.
                log.error("job_processing_rollback_failed", source=connector.name, exc_info=True)
        return "filtered"

    if is_new:
        dedupe_candidates.append(
            ExistingJobRef(
                id=row.id, source=row.source, source_job_id=row.source_job_id,
                company_name=row.company_name, job_title=row.job_title,
                canonical_fingerprint=row.canonical_fingerprint,
            )
        )
        return "new"
    return "updated"


async def _upsert(session: AsyncSession, job: JobDraft, dedupe_candidates: list[ExistingJobRef]):
    row, is_new = await repository.upsert_job(session, job, dedupe_candidates)
    await session.commit()
    return row, is_new
