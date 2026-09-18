import respx
from httpx import Response

from app.connectors.remotive import RemotiveConnector


@respx.mock
async def test_fetch_and_normalize():
    payload = {
        "jobs": [
            {
                "id": 555,
                "title": "Backend Engineer",
                "company_name": "Acme",
                "category": "Software Development",
                "tags": ["python", "django"],
                "job_type": "full_time",
                "publication_date": "2026-06-01T00:00:00",
                "candidate_required_location": "USA Only",
                "salary": "$120,000 - $150,000",
                "description": "<p>Join us.</p>",
                "url": "https://remotive.com/remote-jobs/555",
            }
        ]
    }
    respx.get("https://remotive.com/api/remote-jobs").mock(return_value=Response(200, json=payload))

    connector = RemotiveConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Backend Engineer"
    assert draft.original_location == "USA Only"
    assert draft.employment_type == "full_time"
    assert draft.industry == "Software Development"
    assert draft.salary_min == 120000
    assert draft.salary_max == 150000
    assert draft.is_remote is True
