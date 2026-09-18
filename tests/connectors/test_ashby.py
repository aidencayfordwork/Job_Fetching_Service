import respx
from httpx import Response

from app.connectors.ashby import AshbyConnector
from app.connectors.ats_common import AtsTarget


@respx.mock
async def test_fetch_and_normalize():
    payload = {
        "jobs": [
            {
                "id": "job-1",
                "title": "Senior Infrastructure Engineer",
                "location": "Remote - North America",
                "isRemote": True,
                "workplaceType": "Remote",
                "employmentType": "FullTime",
                "publishedAt": "2026-06-01T00:00:00.000Z",
                "jobUrl": "https://jobs.ashbyhq.com/acme/job-1",
                "applyUrl": "https://jobs.ashbyhq.com/acme/job-1/application",
                "descriptionHtml": "<p>Great role.</p>",
                "descriptionPlain": "Great role.",
                "compensation": {
                    "compensationTierSummary": "$180K - $210K",
                    "compensationTiers": [
                        {
                            "components": [
                                {
                                    "compensationType": "Salary",
                                    "interval": "1 YEAR",
                                    "currencyCode": "USD",
                                    "minValue": 180000,
                                    "maxValue": 210000,
                                }
                            ]
                        }
                    ],
                },
            }
        ]
    }
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=Response(200, json=payload)
    )

    connector = AshbyConnector()
    connector.board_targets = [AtsTarget("Acme", "acme")]

    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Infrastructure Engineer"
    assert draft.is_remote is True
    assert draft.employment_type == "full_time"
    assert draft.original_location == "Remote - North America (Remote)"
    assert draft.salary_min == 180000
    assert draft.salary_max == 210000
    assert draft.currency == "USD"
    assert draft.salary_period == "year"
