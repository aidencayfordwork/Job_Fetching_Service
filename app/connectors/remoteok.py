from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html


class RemoteOkConnector(SourceConnector):
    name = "remoteok"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        async with default_client() as client:

            @with_retry
            async def _get() -> list:
                resp = await client.get("https://remoteok.com/api")
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        for entry in data:
            # The first array element is a metadata/legal-notice blob, not a job.
            if "id" not in entry:
                continue
            if since is not None:
                posted_at = _parse_epoch(entry.get("epoch"))
                if posted_at is not None and posted_at <= since:
                    continue
            yield entry

    def normalize(self, raw: RawJob) -> JobDraft:
        cleaned = clean_html(raw.get("description"))
        tags = sorted({t.strip() for t in raw.get("tags") or [] if t and t.strip()})

        salary_min = raw.get("salary_min") or None
        salary_max = raw.get("salary_max") or None

        return JobDraft(
            source=self.name,
            source_job_id=str(raw["id"]),
            company_name=raw.get("company") or "Unknown",
            job_title=(raw.get("position") or "").strip(),
            source_url=raw.get("url") or raw.get("apply_url"),
            direct_apply_url=raw.get("apply_url") or raw.get("url"),
            original_location=raw.get("location") or None,
            full_technology_stack=tags,
            raw_job_description=raw.get("description"),
            cleaned_job_description=cleaned,
            posted_at=_parse_epoch(raw.get("epoch")),
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            currency="USD" if (salary_min or salary_max) else None,
            salary_period="year" if (salary_min or salary_max) else None,
            raw_payload=raw,
        )


def _parse_epoch(value: int | str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
