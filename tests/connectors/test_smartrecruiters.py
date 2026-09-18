import respx
from httpx import Response

from app.connectors.ats_common import AtsTarget
from app.connectors.smartrecruiters import SmartRecruitersConnector

_LIST_PAGE = {
    "offset": 0,
    "limit": 100,
    "totalFound": 2,
    "content": [
        {
            "id": "111",
            "name": "Senior Backend Engineer",
            "company": {"identifier": "Acme", "name": "Acme"},
            "releasedDate": "2026-09-01T10:00:00.000Z",
            "location": {"city": "Remote", "country": "us", "remote": True, "fullLocation": "Remote - US"},
        },
        {
            # Not remote - should be skipped before any detail fetch.
            "id": "222",
            "name": "Store Associate",
            "company": {"identifier": "Acme", "name": "Acme"},
            "releasedDate": "2026-09-01T10:00:00.000Z",
            "location": {"city": "Austin", "country": "us", "remote": False, "fullLocation": "Austin, TX"},
        },
    ],
}

_DETAIL = {
    "id": "111",
    "name": "Senior Backend Engineer",
    "company": {"identifier": "Acme", "name": "Acme"},
    "location": {"city": "Remote", "country": "us", "remote": True, "fullLocation": "Remote - US"},
    "releasedDate": "2026-09-01T10:00:00.000Z",
    "postingUrl": "https://jobs.smartrecruiters.com/Acme/111",
    "applyUrl": "https://jobs.smartrecruiters.com/Acme/111?oga=true",
    "industry": {"id": "it", "label": "IT Services"},
    "typeOfEmployment": {"id": "full_time", "label": "Full-time"},
    "jobAd": {
        "sections": {
            "jobDescription": {"title": "Job Description", "text": "<p>Build APIs in Python on AWS.</p>"},
            "qualifications": {"title": "Qualifications", "text": "<p>5+ years experience.</p>"},
        }
    },
}


@respx.mock
async def test_fetch_skips_non_remote_and_fetches_detail_for_remote():
    respx.get("https://api.smartrecruiters.com/v1/companies/acme/postings").mock(
        return_value=Response(200, json=_LIST_PAGE)
    )
    respx.get("https://api.smartrecruiters.com/v1/companies/acme/postings/111").mock(
        return_value=Response(200, json=_DETAIL)
    )

    connector = SmartRecruitersConnector()
    connector.board_targets = [AtsTarget("Acme", "acme")]

    raws = [raw async for raw in connector.fetch(since=None)]
    # Only the remote posting triggers a detail fetch; the non-remote one
    # (id 222) never even gets requested.
    assert len(raws) == 1
    assert raws[0]["id"] == "111"

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Backend Engineer"
    assert draft.is_remote is True
    assert draft.employment_type == "full_time"
    assert "Python" in draft.cleaned_job_description
    assert "5+ years" in draft.cleaned_job_description
