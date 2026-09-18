"""Jooble connector.

UNTESTED AGAINST THE LIVE API: Jooble requires a real API key (requested
via a form at https://jooble.org/api/about, not instant - see
architecture.md), which this environment doesn't have. Built against
Jooble's documented request/response format instead of a live response
sample, unlike every other connector in this project. Re-verify against
a real response once a key is available.

The free tier is a 500-CALL LIFETIME cap, not a monthly one - this
connector deliberately makes exactly one request per fetch (a single
page, keyword-filtered) rather than paginating, to conserve that budget.
At the configured 6-hour interval that's 4 calls/day - well within
budget, but pagination would burn through 500 calls in days.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.config import get_settings
from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html, parse_salary


class JoobleConnector(SourceConnector):
    name = "jooble"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        settings = get_settings()
        api_key = settings.jooble_api_key
        if not api_key:
            return

        async with default_client() as client:

            @with_retry
            async def _post() -> dict:
                resp = await client.post(
                    f"https://jooble.org/api/{api_key}",
                    json={"keywords": "software engineer", "location": "United States", "page": "1"},
                )
                resp.raise_for_status()
                return resp.json()

            data = await _post()

        for job in data.get("jobs", []):
            if since is not None:
                updated = _parse_dt(job.get("updated"))
                if updated is not None and updated <= since:
                    continue
            yield job

    def normalize(self, raw: RawJob) -> JobDraft:
        cleaned = clean_html(raw.get("snippet"))
        salary = parse_salary(raw.get("salary"))

        link = raw.get("link")

        return JobDraft(
            source=self.name,
            source_job_id=str(raw.get("id") or link),
            company_name=raw.get("company") or "Unknown",
            job_title=(raw.get("title") or "").strip(),
            source_url=link,
            direct_apply_url=link,
            original_location=raw.get("location") or None,
            employment_type=_map_employment_type(raw.get("type")),
            raw_job_description=raw.get("snippet"),
            cleaned_job_description=cleaned,
            posted_at=_parse_dt(raw.get("updated")),
            salary_min=salary.salary_min,
            salary_max=salary.salary_max,
            currency=salary.currency,
            salary_period=salary.salary_period,
            original_salary_text=raw.get("salary") or salary.original_salary_text,
            raw_payload=raw,
        )


def _map_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    if "full" in lowered:
        return "full_time"
    if "part" in lowered:
        return "part_time"
    if "contract" in lowered or "freelance" in lowered:
        return "contract"
    if "intern" in lowered:
        return "internship"
    return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
