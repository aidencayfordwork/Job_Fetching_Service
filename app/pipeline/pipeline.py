"""Orchestrates the per-job pipeline: Classify -> Filter -> MatchKeywords
-> Dedupe, in that order (see architecture.md §6 for why Classify runs
before Filter).

Deliberately does not touch the database - persistence.repository calls
this once per normalized job and decides what to do with the result
(insert/update/skip), passing in whatever dedup candidates it already
queried.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.connectors.base import JobDraft
from app.pipeline.classify_level import classify_level
from app.pipeline.classify_role import classify_role
from app.pipeline.classify_stack import classify_stack
from app.pipeline.dedupe import ExistingJobRef, find_duplicate
from app.pipeline.filters import apply_filters
from app.pipeline.match_keywords import match_keywords


@dataclass(frozen=True, slots=True)
class PipelineResult:
    kept: bool
    reason: str | None
    job: JobDraft
    duplicate_of: ExistingJobRef | None


def process_job(job: JobDraft, dedupe_candidates: list[ExistingJobRef] | None = None) -> PipelineResult:
    classify_level(job)
    classify_role(job)
    classify_stack(job)

    outcome = apply_filters(job)
    if not outcome.kept:
        return PipelineResult(kept=False, reason=outcome.reason, job=job, duplicate_of=None)

    job.matched_keywords = match_keywords(job.job_title, job.cleaned_job_description)

    duplicate = find_duplicate(job, dedupe_candidates) if dedupe_candidates else None

    return PipelineResult(kept=True, reason=None, job=job, duplicate_of=duplicate)
