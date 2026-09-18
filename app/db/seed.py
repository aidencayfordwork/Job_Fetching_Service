"""Idempotent seed for the `sources` table.

Populates one row per implemented or planned source (§5.2 of
architecture.md) so the `sources` table — and the scheduler — has
something to iterate over. `enabled` reflects real state: True once a
source has a working connector, False if it's implemented but needs
credentials that only the user can provision (Adzuna, Jooble), or absent
entirely if there's no official API to build against (Y Combinator/Work
at a Startup - confirmed no public API exists, and LinkedIn/Indeed/
Glassdoor/ZipRecruiter/Built In/Otta/HiringCafe - explicit ToS
prohibitions, see architecture.md §5.2/§5.3).

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
    {"name": "greenhouse", "kind": "ats", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "lever", "kind": "ats", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "ashby", "kind": "ats", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "smartrecruiters", "kind": "ats", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "remoteok", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "himalayas", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "jobicy", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    {"name": "weworkremotely", "kind": "rss", "fetch_interval_seconds": ONE_HOUR, "enabled": True},
    {"name": "remotive", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS, "enabled": True},
    # Implemented, but disabled until real app_id/app_key or an API key
    # is configured in Settings - see architecture.md for signup links.
    {"name": "adzuna", "kind": "aggregator_api", "fetch_interval_seconds": THREE_HOURS, "enabled": False},
    # Free tier is a 500-call lifetime cap - poll less often to conserve quota.
    {"name": "jooble", "kind": "aggregator_api", "fetch_interval_seconds": SIX_HOURS, "enabled": False},
]


async def seed_sources(session: AsyncSession) -> int:
    stmt = pg_insert(Source).values(
        [{**row, "config": {}} for row in SOURCES]
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
