"""APScheduler wiring: one job per enabled source at its own configured
interval (never a single global interval - architecture.md §4 "Fetch
schedule"), plus a periodic discovery job. `max_instances=1` per job is
the per-source lock: a still-running fetch skips its next scheduled
firing rather than overlapping itself.
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import app.connectors  # noqa: F401 - import side effect registers every connector
from app.config import get_settings
from app.connectors import registry
from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.db.models import Source
from app.scheduler.discovery_job import run_discovery
from app.scheduler.runner import run_source

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_source_by_name(name: str) -> None:
    connector = registry.get(name)
    await run_source(connector)


async def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    async with async_session_factory() as session:
        sources = list(
            (await session.execute(select(Source).where(Source.enabled.is_(True)))).scalars()
        )

    known_connectors = registry.all_connectors()
    for source in sources:
        if source.name not in known_connectors:
            log.warning("enabled_source_missing_connector", source=source.name)
            continue
        scheduler.add_job(
            _run_source_by_name,
            "interval",
            seconds=source.fetch_interval_seconds,
            args=[source.name],
            id=f"fetch:{source.name}",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(),
        )

    scheduler.add_job(
        run_discovery,
        "interval",
        seconds=settings.discovery_interval_seconds,
        id="discovery",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )

    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler_started", sources=[s.name for s in sources if s.name in known_connectors])
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


async def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
