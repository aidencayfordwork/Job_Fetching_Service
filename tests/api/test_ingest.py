from app.db.models import Job

_VALID_SUBMISSION = {
    "source_url": "https://www.linkedin.com/jobs/view/1234567890",
    "company_name": "Ingest Test Co",
    "job_title": "Senior Backend Engineer",
    "raw_job_description": (
        "We build backend services in Python and Go on AWS using Kubernetes "
        "and PostgreSQL. This is a fully remote role open to candidates "
        "based in the United States. Compensation: $170,000 - $210,000 per year."
    ),
}


async def test_submit_requires_api_key(client):
    resp = await client.post("/jobs/submit", json=_VALID_SUBMISSION)
    assert resp.status_code == 401


async def test_submit_validates_required_fields(client, api_headers):
    resp = await client.post("/jobs/submit", json={"company_name": "Acme"}, headers=api_headers)
    assert resp.status_code == 422


async def test_submit_creates_a_new_job_through_the_real_pipeline(client, api_headers, db_session):
    resp = await client.post("/jobs/submit", json=_VALID_SUBMISSION, headers=api_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "created"
    assert body["job_id"] is not None

    row = await db_session.get(Job, body["job_id"])
    assert row.company_name == "Ingest Test Co"
    assert row.job_title == "Senior Backend Engineer"
    assert row.level == "SENIOR"
    assert row.role_category == "Backend"
    assert "Python" in row.full_technology_stack
    assert row.source == "linkedin"
    assert row.salary_min == 170000
    assert row.remote_scope == "US"


async def test_submit_rejects_a_job_that_fails_filters(client, api_headers):
    submission = dict(_VALID_SUBMISSION)
    submission["source_url"] = "https://www.linkedin.com/jobs/view/9999999999"
    submission["raw_job_description"] = "This is a hybrid role, 3 days a week in our NYC office."
    submission["original_location"] = "New York, NY"

    resp = await client.post("/jobs/submit", json=submission, headers=api_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["reason"] == "not_confirmed_remote"
    assert body["job_id"] is None


async def test_resubmitting_the_same_url_updates_rather_than_duplicates(client, api_headers, db_session):
    submission = dict(_VALID_SUBMISSION)
    submission["source_url"] = "https://www.linkedin.com/jobs/view/5555555555"

    first = await client.post("/jobs/submit", json=submission, headers=api_headers)
    assert first.json()["status"] == "created"
    first_id = first.json()["job_id"]

    submission["job_title"] = "Senior Backend Engineer II"
    second = await client.post("/jobs/submit", json=submission, headers=api_headers)
    body = second.json()
    assert body["status"] == "updated"
    assert body["job_id"] == first_id

    row = await db_session.get(Job, first_id)
    assert row.job_title == "Senior Backend Engineer II"


async def test_submit_duplicate_of_existing_ats_job_stays_canonical(client, api_headers, db_session):
    # A job already fetched from Greenhouse (the canonical, higher-
    # priority source) exists first.
    existing = Job(
        company_name="Dedup Test Co", job_title="Senior Backend Engineer",
        source="greenhouse", source_job_id="gh-1", source_url="https://boards.greenhouse.io/dedup/1",
        remote_scope="US", canonical_fingerprint="fp-dedup-test-1", active=True,
    )
    db_session.add(existing)
    await db_session.flush()

    submission = dict(_VALID_SUBMISSION)
    submission["source_url"] = "https://www.linkedin.com/jobs/view/7777777777"
    submission["company_name"] = "Dedup Test Co"
    submission["job_title"] = "Senior Backend Engineer"

    resp = await client.post("/jobs/submit", json=submission, headers=api_headers)
    body = resp.json()
    assert body["status"] == "duplicate"
    assert body["job_id"] == existing.id

    await db_session.refresh(existing)
    # The Greenhouse posting stays canonical - a LinkedIn submission
    # doesn't outrank it (dedupe.SOURCE_PRIORITY).
    assert existing.source == "greenhouse"
