from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_api_key
from app.db.models import AtsCompany, SourceRun
from app.persistence.repository import get_source_by_name
from app.schemas.source import AtsCompanyOut, SourceHealthOut, SourceRunOut
from app.scheduler.health import get_source_health, list_all_source_health

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/sources", response_model=list[SourceHealthOut])
async def list_sources(session: AsyncSession = Depends(get_session)) -> list[SourceHealthOut]:
    health_rows = await list_all_source_health(session)
    return [SourceHealthOut(**asdict(h)) for h in health_rows]


@router.get("/sources/{name}/runs", response_model=list[SourceRunOut])
async def get_source_runs(
    name: str,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SourceRunOut]:
    source_row = await get_source_by_name(session, name)
    if source_row is None:
        raise HTTPException(status_code=404, detail="Unknown source")

    stmt = (
        select(SourceRun)
        .where(SourceRun.source_id == source_row.id)
        .order_by(SourceRun.started_at.desc(), SourceRun.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [SourceRunOut.model_validate(row) for row in rows]


@router.get("/sources/{name}/health", response_model=SourceHealthOut)
async def get_source_health_route(name: str, session: AsyncSession = Depends(get_session)) -> SourceHealthOut:
    health = await get_source_health(session, name)
    if health is None:
        raise HTTPException(status_code=404, detail="Unknown source")
    return SourceHealthOut(**asdict(health))


@router.get("/ats-companies", response_model=list[AtsCompanyOut])
async def list_ats_companies(
    session: AsyncSession = Depends(get_session),
    ats_platform: str | None = None,
    enabled_only: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AtsCompanyOut]:
    stmt = select(AtsCompany)
    if ats_platform:
        stmt = stmt.where(AtsCompany.ats_platform == ats_platform)
    if enabled_only:
        stmt = stmt.where(AtsCompany.enabled.is_(True))
    stmt = stmt.order_by(AtsCompany.discovered_at.desc()).limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    return [AtsCompanyOut.model_validate(row) for row in rows]
