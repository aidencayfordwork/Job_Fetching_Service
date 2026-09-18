from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html

# 200 is the observed effective cap regardless of a higher requested count.
_MAX_COUNT = 200

_JOB_TYPE_MAP = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "freelance": "contract",
    "internship": "internship",
}


class JobicyConnector(SourceConnector):
    name = "jobicy"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        async with default_client() as client:

            @with_retry
            async def _get() -> dict:
                resp = await client.get("https://jobicy.com/api/v2/remote-jobs", params={"count": _MAX_COUNT})
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        for job in data.get("jobs", []):
            if since is not None:
                posted_at = _parse_dt(job.get("pubDate"))
                if posted_at is not None and posted_at <= since:
                    continue
            yield job

    def normalize(self, raw: RawJob) -> JobDraft:
        cleaned = clean_html(raw.get("jobDescription"))
        job_type = (raw.get("jobType") or [None])[0]

        return JobDraft(
            source=self.name,
            source_job_id=str(raw["id"]),
            company_name=raw.get("companyName") or "Unknown",
            job_title=(raw.get("jobTitle") or "").strip(),
            source_url=raw["url"],
            direct_apply_url=raw["url"],
            original_location=raw.get("jobGeo") or None,
            # Jobicy is a remote-only job board by definition of the site.
            is_remote=True,
            employment_type=_JOB_TYPE_MAP.get((job_type or "").lower()),
            industry=(raw.get("jobIndustry") or [None])[0],
            raw_job_description=raw.get("jobDescription"),
            cleaned_job_description=cleaned,
            posted_at=_parse_dt(raw.get("pubDate")),
            salary_min=raw.get("salaryMin"),
            salary_max=raw.get("salaryMax"),
            currency=raw.get("salaryCurrency"),
            salary_period="year" if raw.get("salaryPeriod") == "yearly" else raw.get("salaryPeriod"),
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
