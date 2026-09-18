from app.db.models import Job


async def test_stats_requires_api_key(client):
    resp = await client.get("/stats")
    assert resp.status_code == 401


async def test_stats_counts_active_jobs(client, api_headers, db_session):
    db_session.add(
        Job(
            company_name="Stats Test Co", job_title="Senior Backend Engineer",
            source="greenhouse", source_job_id="stats-test-1", source_url="https://x/1",
            canonical_fingerprint="fp-stats-1", active=True,
        )
    )
    await db_session.flush()

    resp = await client.get("/stats", headers=api_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_active_jobs"] >= 1
    assert body["jobs_added_today"] >= 1
