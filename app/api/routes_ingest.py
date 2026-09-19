"""POST /jobs/submit: ingestion for jobs found manually (e.g. by a human
browsing LinkedIn - no scraping involved) rather than fetched by a
connector. Runs through the same pipeline and exclusion rules as every
scheduled fetch (app/pipeline/submission.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_api_key
from app.pipeline.submission import ingest_submission
from app.schemas.job import JobSubmission, JobSubmissionResult

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/jobs/submit", response_model=JobSubmissionResult)
async def submit_job(
    submission: JobSubmission, session: AsyncSession = Depends(get_session)
) -> JobSubmissionResult:
    return await ingest_submission(session, submission)
