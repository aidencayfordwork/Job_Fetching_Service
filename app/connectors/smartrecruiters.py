from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from app.connectors.ats_common import AtsMultiCompanyConnector, AtsTarget
from app.connectors.base import JobDraft, RawJob
from app.core.http_client import default_client, with_retry
from app.pipeline.normalize import clean_html

_PAGE_SIZE = 100

_EMPLOYMENT_TYPE_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "temporary": "contract",
    "intern": "internship",
    "other": None,
}


class SmartRecruitersConnector(AtsMultiCompanyConnector):
    name = "smartrecruiters"
    kind = "ats"

    async def _fetch_company(self, target: AtsTarget, since: datetime | None) -> AsyncIterator[RawJob]:
        list_url = f"https://api.smartrecruiters.com/v1/companies/{target.board_token}/postings"

        async with default_client() as client:
            offset = 0
            while True:

                @with_retry
                async def _get_page(offset=offset) -> dict:
                    resp = await client.get(list_url, params={"limit": _PAGE_SIZE, "offset": offset})
                    resp.raise_for_status()
                    return resp.json()

                page = await _get_page()
                items = page.get("content", [])
                if not items:
                    break

                for item in items:
                    if since is not None:
                        released = _parse_dt(item.get("releasedDate"))
                        if released is not None and released <= since:
                            continue

                    # SmartRecruiters tells us directly whether a posting is
                    # remote in the list response - skip the expensive
                    # detail fetch entirely for ones that definitely aren't,
                    # since the pipeline would reject them anyway. Real
                    # savings: SmartRecruiters customers skew toward large
                    # retail/service companies with hundreds of mostly
                    # in-person postings.
                    location = item.get("location") or {}
                    if location.get("remote") is False:
                        continue

                    detail_url = f"{list_url}/{item['id']}"

                    @with_retry
                    async def _get_detail(url=detail_url) -> dict:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        return resp.json()

                    try:
                        detail = await _get_detail()
                    except Exception:
                        continue
                    yield detail

                offset += _PAGE_SIZE
                if offset >= page.get("totalFound", 0):
                    break

    def normalize(self, raw: RawJob) -> JobDraft:
        location = raw.get("location") or {}
        location_text = location.get("fullLocation") or None

        sections = ((raw.get("jobAd") or {}).get("sections")) or {}
        jd_parts = [
            sections[key]["text"]
            for key in ("jobDescription", "qualifications", "additionalInformation")
            if key in sections and sections[key].get("text")
        ]
        raw_jd = "\n\n".join(jd_parts)
        cleaned = clean_html(raw_jd)

        employment_type = _EMPLOYMENT_TYPE_MAP.get(
            ((raw.get("typeOfEmployment") or {}).get("id") or "").lower()
        )

        return JobDraft(
            source=self.name,
            source_job_id=raw["id"],
            company_name=(raw.get("company") or {}).get("name") or raw["_company_name"],
            job_title=raw["name"].strip(),
            source_url=raw.get("postingUrl") or raw.get("ref"),
            direct_apply_url=raw.get("applyUrl") or raw.get("postingUrl"),
            original_location=location_text,
            is_remote=location.get("remote"),
            employment_type=employment_type,
            industry=(raw.get("industry") or {}).get("label"),
            raw_job_description=raw_jd or None,
            cleaned_job_description=cleaned or None,
            posted_at=_parse_dt(raw.get("releasedDate")),
            raw_payload=raw,
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
