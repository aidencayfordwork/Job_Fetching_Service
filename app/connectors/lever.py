from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.connectors.ats_common import AtsMultiCompanyConnector, AtsTarget
from app.connectors.base import JobDraft, RawJob
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html, parse_salary

_EMPLOYMENT_TYPE_MAP = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "intern": "internship",
    "internship": "internship",
}


class LeverConnector(AtsMultiCompanyConnector):
    name = "lever"
    kind = "ats"

    async def _fetch_company(self, target: AtsTarget, since: datetime | None) -> AsyncIterator[RawJob]:
        url = f"https://api.lever.co/v0/postings/{target.board_token}"

        async with default_client() as client:

            @with_retry
            async def _get() -> object:
                resp = await client.get(url, params={"mode": "json"})
                resp.raise_for_status()
                return resp.json()

            data = await _get()

        if not isinstance(data, list):
            # Unknown/removed board (Lever returns {"ok": false, ...}).
            return

        for posting in data:
            if since is not None:
                created_at = _parse_epoch_ms(posting.get("createdAt"))
                if created_at is not None and created_at <= since:
                    continue
            yield posting

    def normalize(self, raw: RawJob) -> JobDraft:
        categories = raw.get("categories") or {}
        location = categories.get("location") or ", ".join(categories.get("allLocations") or []) or None
        workplace_type = raw.get("workplaceType")
        if location and workplace_type:
            location = f"{location} ({workplace_type})"
        elif workplace_type:
            location = workplace_type

        description_plain = raw.get("descriptionPlain") or clean_html(raw.get("description"))
        salary = parse_salary(description_plain + "\n" + (raw.get("additionalPlain") or ""))

        employment_type = _EMPLOYMENT_TYPE_MAP.get(
            (categories.get("commitment") or "").strip().lower(), None
        )

        return JobDraft(
            source=self.name,
            source_job_id=raw["id"],
            company_name=raw["_company_name"],
            job_title=raw["text"].strip(),
            source_url=raw["hostedUrl"],
            direct_apply_url=raw.get("applyUrl") or raw["hostedUrl"],
            original_location=location,
            employment_type=employment_type,
            raw_job_description=raw.get("description"),
            cleaned_job_description=description_plain,
            posted_at=_parse_epoch_ms(raw.get("createdAt")),
            salary_min=salary.salary_min,
            salary_max=salary.salary_max,
            currency=salary.currency,
            salary_period=salary.salary_period,
            original_salary_text=salary.original_salary_text,
            raw_payload=raw,
        )


def _parse_epoch_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
