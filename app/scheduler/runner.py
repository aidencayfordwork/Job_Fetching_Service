"""Fetch -> pipeline -> persist for ONE source.

Isolation is the whole point of this module: a bad company board, a
malformed job, or a mid-run network blip must never take down the whole
run or affect any other source. Each job is committed individually so a
late failure doesn't roll back everything already persisted this run.
"""

from __future__ import annotations

from app.connectors.ats_common import AtsMultiCompanyConnector
from app.connectors.base import SourceConnector
from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.persistence import repository
from app.pipeline.dedupe import ExistingJobRef
from app.pipeline.pipeline import process_job

log = get_logger(__name__)


async def run_source(connector: SourceConnector) -> None:
    async with async_session_factory() as session:
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

        dedupe_candidates = await repository.get_recent_active_jobs(session)

        jobs_fetched = jobs_new = jobs_updated = jobs_filtered_out = 0
        fetch_level_error: str | None = None

        try:
            async for raw in connector.fetch(since):
                jobs_fetched += 1
                outcome = await _process_one(session, connector, raw, dedupe_candidates)
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

        expired = await repository.mark_expired_jobs(session)
        await session.commit()
        if expired:
            log.info("jobs_marked_inactive", source=connector.name, count=expired)


async def _process_one(session, connector: SourceConnector, raw: dict, dedupe_candidates: list[ExistingJobRef]) -> str:
    """Returns 'new' / 'updated' / 'filtered'. Never raises - a single bad
    job must not abort the rest of the run."""
    try:
        draft = connector.normalize(raw)
        result = process_job(draft, dedupe_candidates)

        if not result.kept:
            return "filtered"

        row, is_new = await repository.upsert_job(session, result.job, dedupe_candidates)
        await session.commit()

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
    except Exception:
        await session.rollback()
        log.warning("job_processing_failed", source=connector.name, raw_keys=list(raw.keys()), exc_info=True)
        return "filtered"
