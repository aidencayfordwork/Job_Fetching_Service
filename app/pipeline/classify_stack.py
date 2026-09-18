"""Technology-stack extraction, built on top of match_keywords' taxonomy.

Reuses the same curated vocabulary instead of maintaining a second
technology dictionary — just restricted to the categories that are
actually "a technology" (languages, frameworks, infra, tools), excluding
taxonomy categories that describe concepts/domains rather than named tech
(e.g. "Distributed Systems", "Backend", "Agile").
"""

from __future__ import annotations

from app.connectors.base import JobDraft
from app.pipeline.match_keywords import match_terms_by_category

_STACK_CATEGORIES = (
    "languages",
    "frontend",
    "backend_frameworks",
    "mobile",
    "ai_ml",
    "data_engineering",
    "databases",
    "cloud_infra",
    "devops_sre",
    "testing",
)

# Headline-worthy categories for main_stack: prefer languages and the
# framework/infra categories a candidate would actually list as their
# "main stack" on a resume, over narrower testing-tool detail.
_HEADLINE_CATEGORIES = (
    "languages",
    "frontend",
    "backend_frameworks",
    "mobile",
    "ai_ml",
    "cloud_infra",
)

_MAIN_STACK_SIZE = 4


def classify_stack(job: JobDraft) -> JobDraft:
    """Populate `full_technology_stack` and `main_stack` on `job` in place
    (also returned for chaining) from title + cleaned JD text."""
    by_category = match_terms_by_category(job.job_title, job.cleaned_job_description)

    full_stack: set[str] = set()
    for category in _STACK_CATEGORIES:
        full_stack.update(by_category.get(category, []))

    # Anything the source already told us directly (e.g. RemoteOK/Remotive
    # tags) is real signal too - keep it, it's not invented data.
    full_stack.update(job.full_technology_stack)

    job.full_technology_stack = sorted(full_stack)

    headline: list[str] = []
    for category in _HEADLINE_CATEGORIES:
        for term in by_category.get(category, []):
            if term not in headline:
                headline.append(term)
            if len(headline) >= _MAIN_STACK_SIZE:
                break
        if len(headline) >= _MAIN_STACK_SIZE:
            break

    job.main_stack = headline or sorted(full_stack)[:_MAIN_STACK_SIZE]
    return job
