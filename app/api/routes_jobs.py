from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_api_key
from app.db.models import Job
from app.schemas.job import JobCard, JobDetail, JobListResponse

router = APIRouter(dependencies=[Depends(require_api_key)])


def _apply_filters(
    stmt,
    *,
    level: str | None,
    role_category: str | None,
    technology: str | None,
    keyword: str | None,
    company: str | None,
    salary_min: float | None,
    salary_max: float | None,
    source: str | None,
    q: str | None,
):
    if level:
        stmt = stmt.where(Job.level == level)
    if role_category:
        stmt = stmt.where(Job.role_category == role_category)
    if technology:
        stmt = stmt.where(Job.full_technology_stack.any(technology))
    if keyword:
        stmt = stmt.where(Job.matched_keywords.any(keyword))
    if company:
        stmt = stmt.where(Job.company_name.ilike(f"%{company}%"))
    if salary_min is not None:
        stmt = stmt.where((Job.salary_max.is_(None)) | (Job.salary_max >= salary_min))
    if salary_max is not None:
        stmt = stmt.where((Job.salary_min.is_(None)) | (Job.salary_min <= salary_max))
    if source:
        stmt = stmt.where(Job.source == source)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(Job.job_title.ilike(pattern) | Job.company_name.ilike(pattern))
    return stmt


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    level: str | None = None,
    role_category: str | None = None,
    technology: str | None = None,
    keyword: str | None = None,
    company: str | None = None,
    salary_min: float | None = None,
    salary_max: float | None = None,
    source: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JobListResponse:
    base = select(Job).where(Job.active.is_(True))
    base = _apply_filters(
        base, level=level, role_category=role_category, technology=technology,
        keyword=keyword, company=company, salary_min=salary_min, salary_max=salary_max,
        source=source, q=q,
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = await session.scalar(count_stmt) or 0

    list_stmt = (
        base.order_by(Job.posted_at.desc().nullslast(), Job.last_seen_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(list_stmt)).scalars().all()

    return JobListResponse(
        items=[JobCard.model_validate(row) for row in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/jobs/new", response_model=JobListResponse)
async def list_new_jobs(
    since: datetime,
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> JobListResponse:
    """Convenience for the Job Application Service to poll "what's new
    since I last checked"."""
    base = select(Job).where(Job.active.is_(True), Job.last_seen_at > since)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = await session.scalar(count_stmt) or 0

    list_stmt = base.order_by(Job.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(list_stmt)).scalars().all()

    return JobListResponse(
        items=[JobCard.model_validate(row) for row in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)) -> JobDetail:
    row = await session.get(Job, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetail.model_validate(row)
