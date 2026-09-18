from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime

from app.connectors.base import JobDraft, RawJob, SourceConnector
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html, parse_salary

_FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


class WeWorkRemotelyConnector(SourceConnector):
    name = "weworkremotely"
    kind = "rss"

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        async with default_client() as client:

            @with_retry
            async def _get() -> str:
                resp = await client.get(_FEED_URL)
                resp.raise_for_status()
                return resp.text

            xml_text = await _get()

        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            raw = {
                "title": item.findtext("title") or "",
                "region": item.findtext("region") or "",
                "category": item.findtext("category") or "",
                "description": item.findtext("description") or "",
                "link": item.findtext("link") or "",
                "guid": item.findtext("guid") or "",
                "pubDate": item.findtext("pubDate") or "",
            }
            if not raw["link"]:
                continue
            if since is not None:
                posted_at = _parse_rfc2822(raw["pubDate"])
                if posted_at is not None and posted_at <= since:
                    continue
            yield raw

    def normalize(self, raw: RawJob) -> JobDraft:
        title = raw["title"]
        if ": " in title:
            company_name, job_title = title.split(": ", 1)
        else:
            company_name, job_title = "Unknown", title

        link = raw["link"]
        source_job_id = link.rstrip("/").rsplit("/", 1)[-1]

        cleaned = clean_html(raw.get("description"))
        salary = parse_salary(cleaned)

        return JobDraft(
            source=self.name,
            source_job_id=source_job_id,
            company_name=company_name.strip(),
            job_title=job_title.strip(),
            source_url=link,
            direct_apply_url=link,
            original_location=raw.get("region") or None,
            industry=raw.get("category") or None,
            raw_job_description=raw.get("description"),
            cleaned_job_description=cleaned,
            posted_at=_parse_rfc2822(raw.get("pubDate")),
            salary_min=salary.salary_min,
            salary_max=salary.salary_max,
            currency=salary.currency,
            salary_period=salary.salary_period,
            original_salary_text=salary.original_salary_text,
            raw_payload=raw,
        )


def _parse_rfc2822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
