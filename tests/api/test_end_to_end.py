"""Full pipeline, start to finish: a mocked connector HTTP response goes
through the real scheduler.run_source() -> classify -> filter -> match
keywords -> dedupe -> persist, and is then verified through the real REST
API. Same code path a live fetch cycle takes; only the outbound HTTP call
is mocked (this test doesn't hit greenhouse.io - see test_greenhouse.py
etc. for that live-API verification, done manually during development).
"""

from datetime import UTC, datetime, timedelta

import respx
from httpx import Response

from app.connectors.greenhouse import GreenhouseConnector
from app.db.models import AtsCompany, Source
from app.scheduler.runner import run_source

# Dates relative to "now" rather than hardcoded, so this test keeps
# passing regardless of when it runs - these jobs need to land inside the
# filter stage's rolling max_job_age_days window (architecture.md §2B),
# not just before some fixed calendar date.
_RECENT = (datetime.now(UTC) - timedelta(days=2)).isoformat()

_PAYLOAD = {
    "jobs": [
        {
            "id": 5551234,
            "title": "Senior Backend Engineer",
            "company_name": "E2E Test Co",
            "absolute_url": "https://boards.greenhouse.io/e2etestco/jobs/5551234",
            "location": {"name": "Remote - US"},
            "content": (
                "&lt;p&gt;We build backend services in Python and Go on AWS "
                "using Kubernetes and PostgreSQL. Compensation: "
                "$170,000 - $210,000 per year. Ability to obtain a security "
                "clearance is a plus.&lt;/p&gt;"
            ),
            "updated_at": _RECENT,
            "first_published": _RECENT,
        },
        {
            # Should be filtered out: hybrid, not fully remote.
            "id": 5551235,
            "title": "Senior Backend Engineer",
            "company_name": "E2E Test Co",
            "absolute_url": "https://boards.greenhouse.io/e2etestco/jobs/5551235",
            "location": {"name": "New York, NY (hybrid)"},
            "content": "&lt;p&gt;Hybrid role, 3 days a week in office.&lt;/p&gt;",
            "updated_at": _RECENT,
            "first_published": _RECENT,
        },
        {
            # Should be filtered out: seniority band excluded.
            "id": 5551236,
            "title": "Software Engineering Intern",
            "company_name": "E2E Test Co",
            "absolute_url": "https://boards.greenhouse.io/e2etestco/jobs/5551236",
            "location": {"name": "Remote - US"},
            "content": "&lt;p&gt;Summer internship program.&lt;/p&gt;",
            "updated_at": _RECENT,
            "first_published": _RECENT,
        },
    ]
}


@respx.mock
async def test_full_pipeline_end_to_end(client, api_headers, db_session):
    source = Source(
        name="e2e-test-greenhouse", kind="ats", fetch_interval_seconds=10800,
        enabled=True, config={},
    )
    db_session.add(source)
    # run_source looks up board_targets from ats_companies filtered by
    # connector.name (== ats_platform for a real connector) - not from
    # whatever's set on the connector instance beforehand, so the
    # company list has to come from here, matching real scheduler
    # behavior rather than bypassing it.
    db_session.add(
        AtsCompany(
            company_name="E2E Test Co", ats_platform="e2e-test-greenhouse",
            board_token="e2etestco", source_of_discovery="manual",
            verified=True, enabled=True,
        )
    )
    await db_session.flush()

    respx.get("https://boards-api.greenhouse.io/v1/boards/e2etestco/jobs").mock(
        return_value=Response(200, json=_PAYLOAD)
    )

    connector = GreenhouseConnector()
    connector.name = "e2e-test-greenhouse"  # match the seeded source row

    await run_source(connector, session=db_session)

    # Verify via the real REST API, not a direct DB query - proves the
    # whole stack (persistence -> API schema -> filters) agrees.
    resp = await client.get("/jobs", headers=api_headers, params={"company": "E2E Test Co"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 1  # only the fully-remote, correctly-seniored job survives
    job = body["items"][0]
    assert job["job_title"] == "Senior Backend Engineer"
    assert job["level"] == "SENIOR"
    assert job["role_category"] == "Backend"
    assert set(job["main_stack"]) >= {"Python", "Go", "AWS"}
    assert job["salary_min"] == 170000
    assert job["salary_max"] == 210000
    assert job["remote_scope"] == "US"

    detail_resp = await client.get(f"/jobs/{job['id']}", headers=api_headers)
    detail = detail_resp.json()
    assert "Kubernetes" in detail["full_technology_stack"]
    assert "Python" in detail["matched_keywords"]
    assert detail["requires_active_clearance"] is False  # "ability to obtain" must not trigger this
    assert detail["cleaned_job_description"]

    # Confirm the source_runs bookkeeping matches what actually happened.
    runs_resp = await client.get("/sources/e2e-test-greenhouse/runs", headers=api_headers)
    runs = runs_resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["jobs_fetched"] == 3
    assert runs[0]["jobs_new"] == 1
    assert runs[0]["jobs_filtered_out"] == 2
