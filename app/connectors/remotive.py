from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html, parse_salary

_JOB_TYPE_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "contract": "contract",
    "freelance": "contract",
    "internship": "internship",
}


class RemotiveConnector(SourceConnector):
    name = "remotive"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        async with default_client() as client:

            @with_retry
            async def _get() -> dict:
                resp = await client.get("https://remotive.com/api/remote-jobs")
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        for job in data.get("jobs", []):
            if since is not None:
                posted_at = _parse_dt(job.get("publication_date"))
                if posted_at is not None and posted_at <= since:
                    continue
            yield job

    def normalize(self, raw: RawJob) -> JobDraft:
        cleaned = clean_html(raw.get("description"))
        salary_text = raw.get("salary") or ""
        salary = parse_salary(salary_text or cleaned)
        tags = sorted({t.strip() for t in raw.get("tags") or [] if t and t.strip()})

        return JobDraft(
            source=self.name,
            source_job_id=str(raw["id"]),
            company_name=raw.get("company_name") or "Unknown",
            job_title=(raw.get("title") or "").strip(),
            source_url=raw["url"],
            direct_apply_url=raw["url"],
            original_location=raw.get("candidate_required_location") or None,
            # Remotive is a remote-only job board by definition of the site.
            is_remote=True,
            employment_type=_JOB_TYPE_MAP.get(raw.get("job_type") or ""),
            industry=raw.get("category") or None,
            full_technology_stack=tags,
            raw_job_description=raw.get("description"),
            cleaned_job_description=cleaned,
            posted_at=_parse_dt(raw.get("publication_date")),
            salary_min=salary.salary_min,
            salary_max=salary.salary_max,
            currency=salary.currency,
            salary_period=salary.salary_period,
            original_salary_text=salary.original_salary_text or (salary_text or None),
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Remotive's timestamps have no UTC offset (e.g. "2026-06-01T00:00:00")
    # - fromisoformat leaves that naive. Assume UTC rather than pass a
    # naive datetime downstream, where comparing it to an aware one raises.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
