"""Periodic ATS company discovery - the mechanism that grows
ats_companies over time without manual curation (architecture.md §5.4).

Two candidate sources, organic taking priority when a company appears in
both: every distinct company name already sitting in `jobs` (found via
the aggregator connectors), plus the static bootstrap seed list. Anything
already in `ats_companies` is skipped.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.base import async_session_factory
from app.db.models import AtsCompany, Job
from app.discovery.probe import probe_company
from app.discovery.seed_sources import load_static_seed_companies

log = get_logger(__name__)


async def _build_candidates(session: AsyncSession, limit: int) -> list[tuple[str, str]]:
    """Returns [(display_name, origin)], deduped, organic taking priority."""
    already_known = {
        name.lower()
        for name in (await session.execute(select(AtsCompany.company_name))).scalars()
    }

    candidate_map: dict[str, tuple[str, str]] = {}

    organic_stmt = select(Job.company_name).distinct().limit(limit * 2)
    for name in (await session.execute(organic_stmt)).scalars():
        key = name.strip().lower()
        if key and key not in already_known:
            candidate_map[key] = (name.strip(), "organic")

    for name in load_static_seed_companies():
        key = name.strip().lower()
        if key and key not in already_known and key not in candidate_map:
            candidate_map[key] = (name.strip(), "seed_static")

    return list(candidate_map.values())[:limit]


async def run_discovery(candidate_limit: int = 200, session: AsyncSession | None = None) -> None:
    """`session`: pass one in to reuse an existing session (mainly for
    tests); otherwise a fresh one is opened and closed here."""
    if session is not None:
        await _run_discovery(session, candidate_limit)
        return

    async with async_session_factory() as owned_session:
        await _run_discovery(owned_session, candidate_limit)


async def _run_discovery(session: AsyncSession, candidate_limit: int) -> None:
    candidates = await _build_candidates(session, candidate_limit)

    discovered = 0
    for display_name, origin in candidates:
        try:
            hits = await probe_company(display_name)
        except Exception:
            log.warning("discovery_probe_failed", company=display_name, exc_info=True)
            continue

        for hit in hits:
            stmt = (
                pg_insert(AtsCompany)
                .values(
                    company_name=display_name, ats_platform=hit.ats_platform,
                    board_token=hit.board_token, source_of_discovery=origin,
                    verified=True, enabled=True,
                )
                .on_conflict_do_nothing(index_elements=["ats_platform", "board_token"])
            )
            result = await session.execute(stmt)
            if result.rowcount:
                discovered += 1

        if hits:
            await session.commit()

    log.info("discovery_run_complete", candidates_checked=len(candidates), discovered=discovered)
