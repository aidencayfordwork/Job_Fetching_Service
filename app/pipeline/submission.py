"""Ingest one manually found job (e.g. a LinkedIn link a person submitted)
through the exact same pipeline and exclusion rules as fetched jobs.
Shared by POST /jobs/submit and the publish reconciliation, which re-imports
manual jobs from BidFlow's feed if the platform's own copy was lost."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import JobDraft
from app.db.models import Job
from app.persistence import repository
from app.pipeline.normalize import clean_html, parse_salary
from app.pipeline.pipeline import process_job
from app.schemas.job import JobSubmission, JobSubmissionResult


async def ingest_submission(
    session: AsyncSession, submission: JobSubmission, source_job_id: str | None = None
) -> JobSubmissionResult:
    """`source_job_id` defaults to a hash of the URL, so re-submitting the same
    link updates rather than duplicates; reconciliation passes the key the job
    already has in BidFlow's feed."""
    source_url = str(submission.source_url)
    source_job_id = source_job_id or hashlib.sha256(source_url.encode("utf-8")).hexdigest()

    cleaned = clean_html(submission.raw_job_description)
    # Same as every connector: the explicit salary text if given, else the JD.
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

    # Checked explicitly (the same identity upsert_job keys its fast path on):
    # process_job's duplicate pre-check matches on fingerprint/fuzzy title, so
    # a re-submitted URL would otherwise be misreported as "duplicate".
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
