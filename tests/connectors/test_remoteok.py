import respx
from httpx import Response

from app.connectors.remoteok import RemoteOkConnector


@respx.mock
async def test_fetch_skips_metadata_entry_and_normalizes():
    payload = [
        {"last_updated": 1735689600, "legal": "API Terms..."},
        {
            "id": "999",
            "epoch": 1735689600,
            "company": "Acme",
            "position": "Senior Python Engineer",
            "tags": ["python", "python", "aws"],
            "description": "Great job. Please mention the word BANANA when applying.",
            "location": "",
            "url": "https://remoteok.com/remote-jobs/999",
            "apply_url": "https://remoteok.com/remote-jobs/999",
            "salary_min": 140000,
            "salary_max": 170000,
        },
    ]
    respx.get("https://remoteok.com/api").mock(return_value=Response(200, json=payload))

    connector = RemoteOkConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Python Engineer"
    assert draft.full_technology_stack == ["aws", "python"]
    assert "BANANA" not in draft.cleaned_job_description
    assert draft.salary_min == 140000
    assert draft.currency == "USD"
