from datetime import UTC, datetime, timedelta

import respx
from httpx import Response

from app.connectors.himalayas import HimalayasConnector


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _job(job_id: str, pub_dt: datetime, **overrides) -> dict:
    base = {
        "title": "Backend Engineer",
        "companyName": "Acme",
        "employmentType": "Full Time",
        "locationRestrictions": ["United States"],
        "description": "<p>Build APIs.</p>",
        "pubDate": _epoch(pub_dt),
        "minSalary": 140000,
        "maxSalary": 170000,
        "currency": "USD",
        "salaryPeriod": "annual",
        "applicationLink": f"https://himalayas.app/jobs/{job_id}",
        "guid": f"https://himalayas.app/jobs/{job_id}",
    }
    base.update(overrides)
    return base


@respx.mock
async def test_fetch_and_normalize():
    now = datetime.now(UTC)
    payload = {
        "totalCount": 1,
        "nextCursor": None,
        "jobs": [_job("1", now - timedelta(hours=2))],
    }
    respx.get("https://himalayas.app/jobs/api").mock(return_value=Response(200, json=payload))

    connector = HimalayasConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Backend Engineer"
    assert draft.original_location == "United States"
    assert draft.is_remote is True
    assert draft.employment_type == "full_time"
    assert draft.salary_min == 140000
    assert draft.salary_period == "year"
    # categories/parentCategories must never leak into full_technology_stack.
    assert draft.full_technology_stack == []


@respx.mock
async def test_fetch_stops_paginating_once_past_age_cutoff():
    now = datetime.now(UTC)
    page1 = {
        "totalCount": 3,
        "nextCursor": "cursor-2",
        "jobs": [_job("recent-1", now - timedelta(hours=1)), _job("recent-2", now - timedelta(hours=2))],
    }
    page2 = {
        "totalCount": 3,
        "nextCursor": "cursor-3",
        # This job is older than max_job_age_days (default 7) - fetch
        # should stop here and never request a page 3.
        "jobs": [_job("too-old", now - timedelta(days=30))],
    }

    route = respx.get("https://himalayas.app/jobs/api")
    route.side_effect = [Response(200, json=page1), Response(200, json=page2)]

    connector = HimalayasConnector()
    raws = [raw async for raw in connector.fetch(since=None)]

    ids = {raw["guid"] for raw in raws}
    assert ids == {"https://himalayas.app/jobs/recent-1", "https://himalayas.app/jobs/recent-2"}
    assert route.call_count == 2  # never fetched a hypothetical page 3
