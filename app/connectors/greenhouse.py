from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.connectors.ats_common import AtsMultiCompanyConnector, AtsTarget
from app.connectors.base import JobDraft, RawJob
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html, parse_salary


class GreenhouseConnector(AtsMultiCompanyConnector):
    name = "greenhouse"
    kind = "ats"

    async def _fetch_company(self, target: AtsTarget, since: datetime | None) -> AsyncIterator[RawJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{target.board_token}/jobs"

        async with default_client() as client:

            @with_retry
            async def _get() -> dict:
                resp = await client.get(url, params={"content": "true"})
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        for job in data.get("jobs", []):
            if since is not None:
                updated_at = _parse_dt(job.get("updated_at"))
                if updated_at is not None and updated_at <= since:
                    continue
            yield job

    def normalize(self, raw: RawJob) -> JobDraft:
        location = (raw.get("location") or {}).get("name")
        cleaned = clean_html(raw.get("content"))
        salary = parse_salary(cleaned)

        return JobDraft(
            source=self.name,
            source_job_id=str(raw["id"]),
            company_name=raw.get("company_name") or raw["_company_name"],
            job_title=raw["title"].strip(),
            source_url=raw["absolute_url"],
            direct_apply_url=raw["absolute_url"],
            original_location=location,
            raw_job_description=raw.get("content"),
            cleaned_job_description=cleaned,
            posted_at=_parse_dt(raw.get("first_published")),
            source_updated_at=_parse_dt(raw.get("updated_at")),
            salary_min=salary.salary_min,
            salary_max=salary.salary_max,
            currency=salary.currency,
            salary_period=salary.salary_period,
            original_salary_text=salary.original_salary_text,
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
