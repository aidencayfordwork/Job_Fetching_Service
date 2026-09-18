"""Adzuna connector.

Verified live once real app_id/app_key credentials were provided (free,
instant signup at https://developer.adzuna.com/signup). Every field name
matched what was built from documented API format ahead of time. One
real gap found live: `salary_min`/`salary_max` come back as `0` rather
than omitted when unstated (same placeholder pattern as RemoteOK) -
handled with the same `or None` fix.

Adzuna's search API returns a truncated description snippet, not the
full original JD text (they link out to the original posting instead) -
so `cleaned_job_description` here will be shorter than other sources',
and classify_stack/match_keywords have less text to work with.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.config import get_settings
from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html

_RESULTS_PER_PAGE = 50
_MAX_PAGES = 10  # safety cap; free tier is ~1,000 calls/month regardless

_CONTRACT_TIME_MAP = {"full_time": "full_time", "part_time": "part_time"}


class AdzunaConnector(SourceConnector):
    name = "adzuna"
    kind = "aggregator_api"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        settings = get_settings()
        app_id = settings.adzuna_app_id
        app_key = settings.adzuna_app_key
        if not app_id or not app_key:
            return

        async with default_client() as client:
            for page in range(1, _MAX_PAGES + 1):

                @with_retry
                async def _get_page(page=page) -> dict:
                    resp = await client.get(
                        f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                        params={
                            "app_id": app_id,
                            "app_key": app_key,
                            "results_per_page": _RESULTS_PER_PAGE,
                            "content-type": "application/json",
                            # Without a keyword, Adzuna's newest-first feed
                            # is dominated by high-volume industries (verified
                            # live: trucking/logistics/healthcare crowded out
                            # every engineering result in the first 200
                            # unfiltered, newest-sorted jobs). This still
                            # returns a good mix of role families (backend,
                            # embedded, AI, etc.) since it's a general text
                            # search, not an exact-phrase match.
                            "what": "software engineer",
                            "sort_by": "date",
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()

                data = await _get_page()
                results = data.get("results", [])
                if not results:
                    break

                reached_cutoff = False
                for job in results:
                    if since is not None:
                        created = _parse_dt(job.get("created"))
                        if created is not None and created <= since:
                            reached_cutoff = True
                            break
                    yield job

                if reached_cutoff or len(results) < _RESULTS_PER_PAGE:
                    break

    def normalize(self, raw: RawJob) -> JobDraft:
        company = (raw.get("company") or {}).get("display_name") or "Unknown"
        location = (raw.get("location") or {}).get("display_name")
        category = (raw.get("category") or {}).get("label")

        cleaned = clean_html(raw.get("description"))

        # Adzuna flags ML-predicted salary estimates distinctly from
        # employer-stated ones - treat a predicted figure as unknown
        # rather than presenting a model's guess as fact. It also uses
        # 0 as a "not stated" placeholder (confirmed live) rather than
        # omitting the field, same as RemoteOK - `or None` treats that
        # placeholder as unknown instead of a literal $0 salary.
        is_predicted = str(raw.get("salary_is_predicted", "0")) == "1"
        salary_min = None if is_predicted else (raw.get("salary_min") or None)
        salary_max = None if is_predicted else (raw.get("salary_max") or None)

        employment_type = _CONTRACT_TIME_MAP.get((raw.get("contract_time") or "").lower())

        apply_url = raw.get("redirect_url")

        return JobDraft(
            source=self.name,
            source_job_id=str(raw["id"]),
            company_name=company,
            job_title=(raw.get("title") or "").strip(),
            source_url=apply_url,
            direct_apply_url=apply_url,
            original_location=location,
            employment_type=employment_type,
            industry=category,
            raw_job_description=raw.get("description"),
            cleaned_job_description=cleaned,
            posted_at=_parse_dt(raw.get("created")),
            salary_min=salary_min,
            salary_max=salary_max,
            currency="USD",
            salary_period="year" if (salary_min or salary_max) else None,
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
