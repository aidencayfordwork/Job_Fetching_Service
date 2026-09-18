from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_api_key
from app.db.models import Job, SourceRun
from app.schemas.source import StatsOut

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/stats", response_model=StatsOut)
async def get_stats(session: AsyncSession = Depends(get_session)) -> StatsOut:
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_24h = now - timedelta(hours=24)

    total_active = await session.scalar(
        select(func.count()).select_from(Job).where(Job.active.is_(True))
    ) or 0

    added_today = await session.scalar(
        select(func.count()).select_from(Job).where(Job.first_seen_at >= today_start)
    ) or 0

    added_last_24h = await session.scalar(
        select(func.count()).select_from(Job).where(Job.first_seen_at >= last_24h)
    ) or 0

    last_fetch_at = await session.scalar(select(func.max(SourceRun.finished_at)))

    return StatsOut(
        total_active_jobs=total_active,
        jobs_added_today=added_today,
        jobs_added_last_24h=added_last_24h,
        last_fetch_at=last_fetch_at,
    )
