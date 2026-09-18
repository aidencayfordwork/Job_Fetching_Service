"""Idempotent seed for the `sources` table.

Populates one row per planned source (§5.2 of architecture.md) so the
`sources` table — and later the scheduler — has something to iterate over
as connectors land. All rows start `enabled=False`: a source is flipped on
only once its connector module actually exists (Phase 4+), so the
scheduler never tries to run a source that isn't implemented yet.

Safe to run repeatedly: uses ON CONFLICT DO NOTHING on the unique `name`,
so it never overwrites interval/enabled changes made after the initial
seed (e.g. via an admin action once a connector is ready).
"""

from __future__ import annotations

import asyncio

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.db.models import Source

log = get_logger(__name__)

THREE_HOURS = 3 * 60 * 60
ONE_HOUR = 60 * 60
SIX_HOURS = 6 * 60 * 60

SOURCES: list[dict] = [
    {"name": "greenhouse", "kind": "ats", "fetch_interval_seconds": THREE_HOURS},
    {"name": "lever", "kind": "ats", "fetch_interval_seconds": THREE_HOURS},
    {"name": "ashby", "kind": "ats", "fetch_interval_seconds": THREE_HOURS},
    {"name": "smartrecruiters", "kind": "ats", "fetch_interval_seconds": THREE_HOURS},
    {"name": "remoteok", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    {"name": "himalayas", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    {"name": "jobicy", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    {"name": "weworkremotely", "kind": "rss", "fetch_interval_seconds": ONE_HOUR},
    {"name": "remotive", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    {"name": "ycombinator", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    {"name": "adzuna", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS},
    # Free tier is a 500-call lifetime cap - poll less often to conserve quota.
    {"name": "jooble", "kind": "aggregator_api", "fetch_interval_seconds": SIX_HOURS},
]


async def seed_sources(session: AsyncSession) -> int:
    stmt = pg_insert(Source).values(
        [{**row, "enabled": False, "config": {}} for row in SOURCES]
    ).on_conflict_do_nothing(index_elements=["name"])
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def main() -> None:
    async with async_session_factory() as session:
        inserted = await seed_sources(session)
        log.info("seed_sources_complete", inserted=inserted, total=len(SOURCES))


if __name__ == "__main__":
    asyncio.run(main())
