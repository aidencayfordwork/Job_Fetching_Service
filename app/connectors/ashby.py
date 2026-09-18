from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.connectors.ats_common import AtsMultiCompanyConnector, AtsTarget
from app.connectors.base import JobDraft, RawJob
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html

_EMPLOYMENT_TYPE_MAP = {
    "fulltime": "full_time",
    "parttime": "part_time",
    "contract": "contract",
    "intern": "internship",
    "internship": "internship",
}

_INTERVAL_TO_PERIOD = {
    "1 YEAR": "year",
    "1 HOUR": "hour",
    "1 MONTH": "month",
}


class AshbyConnector(AtsMultiCompanyConnector):
    name = "ashby"
    kind = "ats"

    async def _fetch_company(self, target: AtsTarget, since: datetime | None) -> AsyncIterator[RawJob]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{target.board_token}"

        async with default_client() as client:

            @with_retry
            async def _get() -> dict:
                resp = await client.get(url, params={"includeCompensation": "true"})
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        for job in data.get("jobs", []):
            if since is not None:
                published_at = _parse_dt(job.get("publishedAt"))
                if published_at is not None and published_at <= since:
                    continue
            yield job

    def normalize(self, raw: RawJob) -> JobDraft:
        location = raw.get("location")
        workplace_type = raw.get("workplaceType")
        if location and workplace_type:
            location = f"{location} ({workplace_type})"
        elif workplace_type:
            location = workplace_type

        description_plain = raw.get("descriptionPlain") or clean_html(raw.get("descriptionHtml"))

        employment_type = _EMPLOYMENT_TYPE_MAP.get((raw.get("employmentType") or "").lower())

        salary_min = salary_max = None
        currency = period = None
        for tier in (raw.get("compensation") or {}).get("compensationTiers") or []:
            for component in tier.get("components") or []:
                if component.get("compensationType") == "Salary" and component.get("minValue"):
                    salary_min = component.get("minValue")
                    salary_max = component.get("maxValue")
                    currency = component.get("currencyCode")
                    period = _INTERVAL_TO_PERIOD.get(component.get("interval"))
                    break
            if salary_min is not None:
                break

        return JobDraft(
            source=self.name,
            source_job_id=raw["id"],
            company_name=raw["_company_name"],
            job_title=raw["title"].strip(),
            source_url=raw["jobUrl"],
            direct_apply_url=raw.get("applyUrl") or raw["jobUrl"],
            original_location=location,
            is_remote=raw.get("isRemote"),
            employment_type=employment_type,
            raw_job_description=raw.get("descriptionHtml"),
            cleaned_job_description=description_plain,
            posted_at=_parse_dt(raw.get("publishedAt")),
            salary_min=salary_min,
            salary_max=salary_max,
            currency=currency,
            salary_period=period,
            original_salary_text=(raw.get("compensation") or {}).get("compensationTierSummary"),
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
