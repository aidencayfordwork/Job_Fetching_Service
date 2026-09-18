from app.db.models import AtsCompany, Source, SourceRun


async def test_list_sources_requires_api_key(client):
    resp = await client.get("/sources")
    assert resp.status_code == 401


async def test_list_sources_includes_seeded_source(client, api_headers, db_session):
    source = Source(name="api-test-source", kind="ats", fetch_interval_seconds=10800, enabled=True, config={})
    db_session.add(source)
    await db_session.flush()

    resp = await client.get("/sources", headers=api_headers)
    assert resp.status_code == 200
    names = [row["source"] for row in resp.json()]
    assert "api-test-source" in names


async def test_get_source_runs(client, api_headers, db_session):
    source = Source(name="api-test-source-2", kind="ats", fetch_interval_seconds=10800, enabled=True, config={})
    db_session.add(source)
    await db_session.flush()
    db_session.add(
        SourceRun(source_id=source.id, status="success", jobs_fetched=5, jobs_new=2, jobs_updated=1, jobs_filtered_out=2)
    )
    await db_session.flush()

    resp = await client.get("/sources/api-test-source-2/runs", headers=api_headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["jobs_new"] == 2


async def test_get_source_runs_unknown_source_404(client, api_headers):
    resp = await client.get("/sources/does-not-exist/runs", headers=api_headers)
    assert resp.status_code == 404


async def test_list_ats_companies(client, api_headers, db_session):
    db_session.add(
        AtsCompany(
            company_name="Api Test Co", ats_platform="greenhouse", board_token="api-test-co",
            source_of_discovery="manual", verified=True, enabled=True,
        )
    )
    await db_session.flush()

    resp = await client.get("/ats-companies", headers=api_headers, params={"ats_platform": "greenhouse"})
    assert resp.status_code == 200
    assert any(row["company_name"] == "Api Test Co" for row in resp.json())
