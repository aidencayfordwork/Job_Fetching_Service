"""Source health summary, built from recent source_runs rows. Backs the
/sources API endpoint and the Source Status frontend page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source, SourceRun


@dataclass(frozen=True, slots=True)
class SourceHealth:
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


async def get_source_health(session: AsyncSession, source_name: str, recent_runs: int = 10) -> SourceHealth | None:
    source_row = await session.scalar(select(Source).where(Source.name == source_name))
    if source_row is None:
        return None

    runs_stmt = (
        select(SourceRun)
        .where(SourceRun.source_id == source_row.id)
        # Postgres's now() is frozen per-transaction, so runs inserted in
        # the same transaction can share an identical started_at - id is
        # a stable tiebreaker for true insertion order.
        .order_by(SourceRun.started_at.desc(), SourceRun.id.desc())
        .limit(recent_runs)
    )
    runs = list((await session.execute(runs_stmt)).scalars())

    last_run = runs[0] if runs else None
    last_success = next((r for r in runs if r.status in ("success", "partial")), None)

    consecutive_failures = 0
    for run in runs:
        if run.status == "failed":
            consecutive_failures += 1
        else:
            break

    return SourceHealth(
        source=source_name,
        enabled=source_row.enabled,
        last_fetch_at=last_run.started_at if last_run else None,
        last_successful_fetch_at=last_success.finished_at if last_success else None,
        last_status=last_run.status if last_run else None,
        consecutive_failures=consecutive_failures,
        jobs_fetched_last_run=last_run.jobs_fetched if last_run else 0,
        jobs_new_last_run=last_run.jobs_new if last_run else 0,
        jobs_updated_last_run=last_run.jobs_updated if last_run else 0,
        errors_last_run=last_run.error_message if last_run else None,
    )


async def list_all_source_health(session: AsyncSession) -> list[SourceHealth]:
    names = (await session.execute(select(Source.name).order_by(Source.name))).scalars()
    results = []
    for name in names:
        health = await get_source_health(session, name)
        if health is not None:
            results.append(health)
    return results
