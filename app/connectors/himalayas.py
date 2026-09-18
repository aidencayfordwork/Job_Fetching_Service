from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html

_PAGE_SIZE = 100
# Himalayas' catalog is huge (100k+ jobs site-wide) with no server-side
# category or date filter, but pagination is newest-first, so we can stop
# once we're past the cutoff instead of scanning the whole thing. This
# caps worst-case pages even if that early-termination logic somehow
# doesn't kick in (e.g. unexpected ordering).
_MAX_PAGES = 50

_EMPLOYMENT_TYPE_MAP = {
    "full time": "full_time",
    "part time": "part_time",
    "contract": "contract",
    "internship": "internship",
    "freelance": "contract",
}


class HimalayasConnector(SourceConnector):
    name = "himalayas"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        settings = get_settings()
        age_cutoff = datetime.now(UTC) - timedelta(days=settings.max_job_age_days)
        cutoff = max(since, age_cutoff) if since is not None else age_cutoff

        async with default_client() as client:
            cursor: str | None = None

            for _ in range(_MAX_PAGES):

                @with_retry
                async def _get_page(cursor=cursor) -> dict:
                    params: dict = {"limit": _PAGE_SIZE}
                    if cursor:
                        params["cursor"] = cursor
                    resp = await client.get("https://himalayas.app/jobs/api", params=params)
                    resp.raise_for_status()
                    return resp.json()

                page = await _get_page()
                jobs = page.get("jobs", [])
                if not jobs:
                    break

                reached_cutoff = False
                for job in jobs:
                    posted_at = _parse_epoch(job.get("pubDate"))
                    if posted_at is not None and posted_at <= cutoff:
                        reached_cutoff = True
                        break
                    yield job

                if reached_cutoff:
                    break

                cursor = page.get("nextCursor")
                if not cursor:
                    break

    def normalize(self, raw: RawJob) -> JobDraft:
        cleaned = clean_html(raw.get("description"))
        location_restrictions = raw.get("locationRestrictions") or []
        employment_type = _EMPLOYMENT_TYPE_MAP.get((raw.get("employmentType") or "").lower())

        return JobDraft(
            source=self.name,
            source_job_id=raw.get("guid") or raw["applicationLink"],
            company_name=raw.get("companyName") or "Unknown",
            job_title=(raw.get("title") or "").strip(),
            source_url=raw["applicationLink"],
            direct_apply_url=raw["applicationLink"],
            original_location=", ".join(location_restrictions) if location_restrictions else None,
            # Himalayas is a remote-only job board by definition of the site.
            is_remote=True,
            employment_type=employment_type,
            # NOTE: `categories`/`parentCategories` are job-function taxonomy
            # slugs (e.g. "Menu-Configuration-Specialist"), not technology
            # names - unlike RemoteOK's tags, so they don't belong in
            # full_technology_stack. classify_stack.py extracts real tech
            # terms from title/JD text later in the pipeline instead.
            raw_job_description=raw.get("description"),
            cleaned_job_description=cleaned,
            posted_at=_parse_epoch(raw.get("pubDate")),
            salary_min=raw.get("minSalary"),
            salary_max=raw.get("maxSalary"),
            currency=raw.get("currency"),
            salary_period="year" if raw.get("salaryPeriod") == "annual" else raw.get("salaryPeriod"),
            raw_payload=raw,
        )


def _parse_epoch(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
