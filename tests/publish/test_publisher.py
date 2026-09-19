"""Publisher against the local BidFlow replica, connected as jobfeed_writer
(JOB_PLATFORM_DB_PROMPT §13)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import FeedPublication, FeedPublishLog, Job
from app.publish.publisher import FeedAuthError, PlannedRow, PublishSummary, _send_batch, run_publish
from tests.publish.conftest import TEST_SOURCE_PREFIX, WRITER_URL

_JD = (
    "<h2>About the role</h2><p>You will build payments APIs.</p>"
    "<h3>Requirements</h3><ul><li>Python and PostgreSQL services on AWS</li>"
    "<li>Kubernetes in production</li><li>Rust for performance-critical paths</li></ul>"
    "<h3>Nice to have</h3><ul><li>Kafka</li></ul>"
    "<p>This is a fully remote role open to candidates anywhere in the United States.</p>"
) * 2


async def _add_job(db_session, **overrides) -> Job:
    tag = uuid.uuid4().hex[:10]
    fields = dict(
        company_name="Pubtest Robotics", job_title="Senior Backend Engineer (Remote)",
        source=f"{TEST_SOURCE_PREFIX}greenhouse", source_job_id=tag,
        source_url=f"https://boards.greenhouse.io/pubtest/jobs/{tag}?utm_source=x",
        original_location="Remote - US", is_remote=True, us_eligible=True, remote_scope="US",
        role_category="Backend", level="SENIOR", employment_type="full_time",
        salary_min=150000, salary_max=180000, currency="USD", salary_period="year",
        original_salary_text="$150,000 - $180,000 per year",
        posted_at=datetime.now(UTC) - timedelta(days=1), raw_job_description=_JD,
        canonical_fingerprint=f"fp-{tag}", active=True,
    )
    fields.update(overrides)
    job = Job(**fields)
    db_session.add(job)
    await db_session.flush()
    return job


async def _feed_row(feed_admin, source: str, source_job_id: str):
    async with feed_admin.connect() as conn:
        return (
            await conn.execute(
                text("SELECT * FROM job_feed.jobs WHERE source = :s AND source_job_id = :i"),
                {"s": source, "i": source_job_id},
            )
        ).mappings().one_or_none()


async def test_publishes_a_verified_job_with_normalized_values(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    summary = await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert summary.results == {"INSERTED": 1}

    row = await _feed_row(feed_admin, job.source, job.source_job_id)
    assert row["country_code"] == "US" and row["work_type"] == "REMOTE" and row["status"] == "ACTIVE"
    assert row["title"] == "Senior Backend Engineer"
    assert row["job_url"] == f"https://boards.greenhouse.io/pubtest/jobs/{job.source_job_id}"
    assert row["company"] == "Pubtest Robotics"
    assert (row["salary_min"], row["salary_max"]) == (150000, 180000)
    assert row["employment_type"] == "FULL_TIME"
    assert "Requirements\n\n- Python and PostgreSQL services on AWS" in row["jd_text"]
    assert row["tags"][0] == "backend"
    assert {"python", "postgresql", "aws", "kubernetes"} <= set(row["tags"])
    assert "kafka" not in row["tags"]
    assert row["unknown_tags"] == ["rust"]  # a real skill BidFlow has no tag for yet

    pub = await db_session.get(FeedPublication, job.id)
    assert (pub.feed_status, pub.last_result) == ("ACTIVE", "INSERTED")


async def test_unchanged_job_is_not_resent_and_updated_at_stays(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    before = await _feed_row(feed_admin, job.source, job.source_job_id)

    summary = await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert summary.skipped_unchanged == 1 and not summary.results

    # Even when an identical row is sent, BidFlow keeps updated_at.
    pub = await db_session.get(FeedPublication, job.id)
    pub.sent_hash = "force-resend"
    summary = await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert summary.results == {"UNCHANGED": 1}
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["updated_at"] == before["updated_at"]


async def test_real_change_updates_without_refreshing_verified_at_twice_a_day(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    before = await _feed_row(feed_admin, job.source, job.source_job_id)

    job.job_title = "Staff Backend Engineer"
    summary = await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert summary.results == {"UPDATED": 1}
    after = await _feed_row(feed_admin, job.source, job.source_job_id)
    assert after["title"] == "Staff Backend Engineer"
    assert after["updated_at"] > before["updated_at"]
    assert after["verified_at"] == before["verified_at"]


async def test_inactive_job_is_closed_not_deleted(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    await run_publish(db_session, feed_engine, job_ids=[job.id])

    job.active = False
    assert (await run_publish(db_session, feed_engine, job_ids=[job.id])).results == {"UPDATED": 1}
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["status"] == "CLOSED"

    job.active = True
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["status"] == "ACTIVE"


async def test_stale_inactive_job_is_expired(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    job.active = False
    job.posted_at = datetime.now(UTC) - timedelta(days=30)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["status"] == "EXPIRED"


async def test_source_promotion_keeps_the_pinned_feed_key(db_session, feed_engine, feed_admin):
    """Cross-source dedup rewrites jobs.source/source_job_id on the same row;
    BidFlow must keep seeing one job, not gain a second live copy."""
    job = await _add_job(db_session, source=f"{TEST_SOURCE_PREFIX}himalayas")
    first_key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])

    job.source, job.source_job_id = f"{TEST_SOURCE_PREFIX}greenhouse", "promoted-" + job.source_job_id
    job.source_url = "https://boards.greenhouse.io/pubtest/jobs/promoted"
    assert (await run_publish(db_session, feed_engine, job_ids=[job.id])).results == {"UPDATED": 1}

    assert (await _feed_row(feed_admin, *first_key))["job_url"] == "https://boards.greenhouse.io/pubtest/jobs/promoted"
    assert await _feed_row(feed_admin, job.source, job.source_job_id) is None


async def test_jobs_that_fail_checks_are_held_back(db_session, feed_engine, feed_admin):
    snippet = await _add_job(db_session, source=f"{TEST_SOURCE_PREFIX}adzuna")
    snippet.source = "adzuna"  # snippet-only source
    abroad = await _add_job(db_session, original_location="Mexico")
    summary = await run_publish(db_session, feed_engine, job_ids=[snippet.id, abroad.id])
    assert summary.held_back == {"description_truncated": 1, "not_verified_us_remote": 1}
    assert not summary.results
    assert await _feed_row(feed_admin, abroad.source, abroad.source_job_id) is None


async def test_published_job_that_stops_verifying_is_closed(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    job.original_location = "Toronto, Canada"
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["status"] == "CLOSED"


async def test_rejected_row_is_logged_and_the_rest_of_the_batch_lands(db_session, feed_engine, feed_admin):
    good, bad = await _add_job(db_session), await _add_job(db_session)
    now = datetime.now(UTC)

    def planned(job, **row_overrides):
        row = dict(
            source=job.source, source_job_id=job.source_job_id, job_url="https://example.com/j",
            jd_text="Full description.", company="Pubtest", title="Senior Engineer", country_code="us",
            work_type="remote", location_text=None, employment_type=None, posted_at=None, verified_at=now,
            salary_min=None, salary_max=None, salary_text=None, tags=["Python", "k8s"], status="active",
        )
        row.update(row_overrides)
        return PlannedRow(job.id, job.source, job.source_job_id, row, "h")

    summary = PublishSummary()
    await _send_batch(
        db_session, feed_engine, [planned(bad, salary_min=-1), planned(good)], {}, now, summary
    )
    assert summary.results == {"REJECTED": 1, "INSERTED": 1}

    landed = await _feed_row(feed_admin, good.source, good.source_job_id)
    assert (landed["country_code"], landed["work_type"], landed["status"]) == ("US", "REMOTE", "ACTIVE")
    assert landed["tags"] == ["python", "k8s"] and landed["unknown_tags"] == []
    assert await _feed_row(feed_admin, bad.source, bad.source_job_id) is None

    log = (await db_session.execute(select(FeedPublishLog).where(FeedPublishLog.job_id == bad.id))).scalar_one()
    assert (log.result, log.constraint_name) == ("REJECTED", "ck_jobs_salary_non_negative")
    assert (await db_session.get(FeedPublication, bad.id)).feed_status is None


async def test_writer_role_cannot_delete(feed_engine):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with feed_engine.begin() as conn:
            await conn.execute(text("DELETE FROM job_feed.jobs WHERE false"))


async def test_bad_password_raises_auth_error(db_session, feed_engine):
    wrong = create_async_engine(WRITER_URL.replace("local-only-change-me", "wrong-password"))
    try:
        with pytest.raises(FeedAuthError):
            await run_publish(db_session, wrong, job_ids=[])
    finally:
        await wrong.dispose()
