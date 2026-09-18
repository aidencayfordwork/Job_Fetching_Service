import respx
from httpx import Response

from app.connectors.jobicy import JobicyConnector


@respx.mock
async def test_fetch_and_normalize():
    payload = {
        "jobCount": 1,
        "jobs": [
            {
                "id": 999,
                "url": "https://jobicy.com/jobs/999-backend-engineer",
                "jobTitle": "Backend Engineer",
                "companyName": "Acme",
                "jobIndustry": ["Engineering"],
                "jobType": ["Full-Time"],
                "jobGeo": "USA",
                "jobDescription": "<p>Build APIs.</p>",
                "pubDate": "2026-09-01T10:00:00+00:00",
                "salaryMin": 140000,
                "salaryMax": 170000,
                "salaryCurrency": "USD",
                "salaryPeriod": "yearly",
            }
        ],
    }
    respx.get("https://jobicy.com/api/v2/remote-jobs").mock(return_value=Response(200, json=payload))

    connector = JobicyConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Backend Engineer"
    assert draft.original_location == "USA"
    assert draft.is_remote is True
    assert draft.employment_type == "full_time"
    assert draft.salary_min == 140000
    assert draft.salary_period == "year"
