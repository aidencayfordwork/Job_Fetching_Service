import respx
from httpx import Response

from app.connectors.ats_common import AtsTarget
from app.connectors.lever import LeverConnector


@respx.mock
async def test_fetch_and_normalize():
    payload = [
        {
            "id": "abc-123",
            "text": "Staff Platform Engineer",
            "categories": {"location": "New York, NY", "commitment": "Full-time", "allLocations": ["New York, NY"]},
            "country": "US",
            "workplaceType": "remote",
            "hostedUrl": "https://jobs.lever.co/acme/abc-123",
            "applyUrl": "https://jobs.lever.co/acme/abc-123/apply",
            "createdAt": 1735689600000,
            "descriptionPlain": "We pay $180,000 - $220,000 per year.",
            "description": "<p>We pay $180,000 - $220,000 per year.</p>",
            "additionalPlain": "",
        }
    ]
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=Response(200, json=payload))

    connector = LeverConnector()
    connector.board_targets = [AtsTarget("Acme", "acme")]

    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.source == "lever"
    assert draft.company_name == "Acme"
    assert draft.job_title == "Staff Platform Engineer"
    assert draft.original_location == "New York, NY (remote)"
    assert draft.employment_type == "full_time"
    assert draft.salary_min == 180000
    assert draft.salary_max == 220000


@respx.mock
async def test_unknown_board_returns_no_jobs():
    respx.get("https://api.lever.co/v0/postings/missing").mock(
        return_value=Response(200, json={"ok": False, "error": "Document not found"})
    )

    connector = LeverConnector()
    connector.board_targets = [AtsTarget("Missing Co", "missing")]

    raws = [raw async for raw in connector.fetch(since=None)]
    assert raws == []
