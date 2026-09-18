"""POST /jobs/submit: ingestion for jobs found manually (e.g. by a human
browsing LinkedIn - no scraping involved, since a person found the link
and the Job Application Service chose to submit it) rather than fetched
by a connector. Runs through the exact same pipeline.process_job() and
repository.upsert_job() as every scheduled fetch, so the exclusion rules
and dedup behavior are guaranteed identical, not a parallel
reimplementation that could drift out of sync.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_api_key
from app.connectors.base import JobDraft
from app.db.models import Job
from app.persistence import repository
from app.pipeline.normalize import clean_html, parse_salary
from app.pipeline.pipeline import process_job
from app.schemas.job import JobSubmission, JobSubmissionResult

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/jobs/submit", response_model=JobSubmissionResult)
async def submit_job(
    submission: JobSubmission, session: AsyncSession = Depends(get_session)
) -> JobSubmissionResult:
    source_url = str(submission.source_url)
    # A stable, always-in-bounds per-URL identifier for the (source,
    # source_job_id) uniqueness constraint - re-submitting the same link
    # is idempotent rather than creating a duplicate row.
    source_job_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()

    cleaned = clean_html(submission.raw_job_description)
    # Same as every connector: try the explicit salary text first (if the
    # caller has it), falling back to parsing it out of the JD body -
    # this was missing entirely before being caught by a test asserting
    # on the real parsed value, not just that *a* value was present.
    salary = parse_salary(submission.original_salary_text or cleaned)

    draft = JobDraft(
        source=submission.source,
        source_job_id=source_job_id,
        company_name=submission.company_name.strip(),
        job_title=submission.job_title.strip(),
        source_url=source_url,
        direct_apply_url=str(submission.direct_apply_url) if submission.direct_apply_url else source_url,
        original_location=submission.original_location,
        posted_at=submission.posted_at,
        salary_min=salary.salary_min,
        salary_max=salary.salary_max,
        currency=salary.currency,
        salary_period=salary.salary_period,
        original_salary_text=submission.original_salary_text or salary.original_salary_text,
        raw_job_description=submission.raw_job_description,
        cleaned_job_description=cleaned,
    )

    dedupe_candidates = await repository.get_recent_active_jobs(session)
    result = process_job(draft, dedupe_candidates)

    if not result.kept:
        return JobSubmissionResult(status="rejected", reason=result.reason)

    # Checked explicitly (mirroring exactly what upsert_job checks first
    # internally) rather than relying on process_job's separate
    # find_duplicate pre-check for this distinction: that pre-check only
    # looks at canonical_fingerprint/fuzzy-title matches, not the
    # (source, source_job_id) identity upsert_job actually keys its fast
    # path on - re-submitting the same URL usually also matches on
    # fingerprint, which would have made "updated" get misreported as
    # "duplicate" if this used that flag instead.
    existing_same_source = await session.scalar(
        select(Job).where(Job.source == draft.source, Job.source_job_id == draft.source_job_id)
    )

    row, is_new = await repository.upsert_job(session, result.job, dedupe_candidates)
    await session.commit()

    if is_new:
        status = "created"
    elif existing_same_source is not None:
        status = "updated"
    else:
        status = "duplicate"

    return JobSubmissionResult(status=status, job_id=row.id)
