import respx
from httpx import Response

from app.connectors.ats_common import AtsTarget
from app.connectors.greenhouse import GreenhouseConnector


@respx.mock
async def test_fetch_and_normalize():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Senior Backend Engineer",
                "company_name": "Acme",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Remote - US"},
                "content": "&lt;p&gt;Build things. Salary: $150,000 - $180,000/year.&lt;/p&gt;",
                "updated_at": "2026-09-01T10:00:00-04:00",
                "first_published": "2026-08-30T10:00:00-04:00",
            }
        ]
    }
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=Response(200, json=payload)
    )

    connector = GreenhouseConnector()
    connector.board_targets = [AtsTarget("Acme", "acme")]

    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.source == "greenhouse"
    assert draft.source_job_id == "123"
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Backend Engineer"
    assert draft.original_location == "Remote - US"
    assert "Build things" in draft.cleaned_job_description
    assert draft.salary_min == 150000
    assert draft.salary_max == 180000


@respx.mock
async def test_since_filters_unchanged_jobs():
    from datetime import UTC, datetime

    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Old Job",
                "company_name": "Acme",
                "absolute_url": "https://x/1",
                "location": {"name": "Remote"},
                "content": "",
                "updated_at": "2026-01-01T00:00:00-00:00",
                "first_published": "2026-01-01T00:00:00-00:00",
            }
        ]
    }
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=Response(200, json=payload)
    )

    connector = GreenhouseConnector()
    connector.board_targets = [AtsTarget("Acme", "acme")]

    since = datetime(2026, 6, 1, tzinfo=UTC)
    raws = [raw async for raw in connector.fetch(since=since)]
    assert raws == []


@respx.mock
async def test_broken_company_does_not_raise():
    respx.get("https://boards-api.greenhouse.io/v1/boards/broken/jobs").mock(
        return_value=Response(404)
    )

    connector = GreenhouseConnector()
    connector.board_targets = [AtsTarget("Broken Co", "broken")]

    raws = [raw async for raw in connector.fetch(since=None)]
    assert raws == []
