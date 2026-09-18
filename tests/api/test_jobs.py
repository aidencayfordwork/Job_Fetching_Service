from app.db.models import Job


def _job_row(**overrides) -> Job:
    defaults = dict(
        company_name="Acme Api Test Co", job_title="Senior Backend Engineer",
        source="greenhouse", source_job_id="api-test-1", source_url="https://x/1",
        direct_apply_url="https://x/1", level="SENIOR", role_category="Backend",
        main_stack=["Python", "AWS"], full_technology_stack=["Python", "AWS", "Docker"],
        matched_keywords=["Python", "AWS", "Backend"], remote_scope="US",
        salary_min=150000, salary_max=180000, currency="USD", salary_period="year",
        canonical_fingerprint="fp-api-test-1", active=True,
    )
    defaults.update(overrides)
    return Job(**defaults)


async def test_list_jobs_requires_api_key(client):
    resp = await client.get("/jobs")
    assert resp.status_code == 401


async def test_list_jobs_returns_active_jobs(client, api_headers, db_session):
    db_session.add(_job_row())
    await db_session.flush()

    resp = await client.get("/jobs", headers=api_headers, params={"company": "Acme Api Test Co"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["company_name"] == "Acme Api Test Co" for item in body["items"])


async def test_list_jobs_excludes_inactive(client, api_headers, db_session):
    db_session.add(
        _job_row(
            company_name="Inactive Only Co", source_job_id="api-test-inactive", active=False,
        )
    )
    await db_session.flush()

    resp = await client.get("/jobs", headers=api_headers, params={"company": "Inactive Only Co"})
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_jobs_filters_by_level_and_technology(client, api_headers, db_session):
    db_session.add(_job_row(source_job_id="api-test-2", level="STAFF", main_stack=["Go"], full_technology_stack=["Go"]))
    await db_session.flush()

    resp = await client.get("/jobs", headers=api_headers, params={"level": "STAFF", "technology": "Go"})
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["level"] == "STAFF" for item in body["items"])


async def test_get_job_detail(client, api_headers, db_session):
    row = _job_row(source_job_id="api-test-3")
    db_session.add(row)
    await db_session.flush()

    resp = await client.get(f"/jobs/{row.id}", headers=api_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_name"] == "Acme Api Test Co"
    assert body["matched_keywords"] == ["Python", "AWS", "Backend"]


async def test_get_job_detail_404(client, api_headers):
    resp = await client.get("/jobs/99999999", headers=api_headers)
    assert resp.status_code == 404


async def test_list_new_jobs_since(client, api_headers, db_session):
    from datetime import UTC, datetime, timedelta

    row = _job_row(source_job_id="api-test-4")
    db_session.add(row)
    await db_session.flush()

    since = datetime.now(UTC) - timedelta(minutes=5)
    resp = await client.get("/jobs/new", headers=api_headers, params={"since": since.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["company_name"] == "Acme Api Test Co" for item in body["items"])
