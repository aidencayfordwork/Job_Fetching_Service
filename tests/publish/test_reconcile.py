"""Rebuilding publish records from BidFlow's feed after the platform's own
records are lost (against the local replica, as jobfeed_writer)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.db.models import FeedPublication, FeedPublishLog, Job, JobAltSource, Source, SourceRun
from app.pipeline.submission import ingest_submission
from app.publish.reconcile import reconcile
from app.publish.publisher import run_publish
from app.schemas.job import JobSubmission
from tests.publish.conftest import TEST_SOURCE_PREFIX
from tests.publish.test_publisher import _JD, _add_job, _feed_row

FETCHED = f"{TEST_SOURCE_PREFIX}greenhouse"


async def _forget_publications(db_session, *job_ids: int) -> None:
    """What a lost or restored platform database looks like."""
    await db_session.execute(delete(FeedPublishLog).where(FeedPublishLog.job_id.in_(job_ids)))
    await db_session.execute(delete(FeedPublication).where(FeedPublication.job_id.in_(job_ids)))
    await db_session.flush()


async def _delete_job(db_session, job: Job) -> None:
    await _forget_publications(db_session, job.id)
    await db_session.execute(delete(JobAltSource).where(JobAltSource.job_id == job.id))
    await db_session.execute(delete(Job).where(Job.id == job.id))
    await db_session.flush()


async def _mark_every_source_fetched(db_session) -> None:
    for source in (await db_session.execute(select(Source).where(Source.enabled.is_(True)))).scalars():
        db_session.add(SourceRun(source_id=source.id, status="success"))
    await db_session.flush()


async def test_lost_records_are_rebuilt_without_resending_anything(db_session, feed_engine, feed_admin):
    jobs = [await _add_job(db_session), await _add_job(db_session, job_title="Staff Platform Engineer")]
    ids = [j.id for j in jobs]
    await run_publish(db_session, feed_engine, job_ids=ids)
    before = [await _feed_row(feed_admin, j.source, j.source_job_id) for j in jobs]

    await _forget_publications(db_session, *ids)
    summary = await run_publish(db_session, feed_engine, job_ids=ids)

    assert summary.reconciled.adopted == 2
    assert not summary.results and summary.skipped_unchanged == 2  # no re-announcement burst
    after = [await _feed_row(feed_admin, j.source, j.source_job_id) for j in jobs]
    assert [r["updated_at"] for r in after] == [r["updated_at"] for r in before]


async def test_job_now_stored_under_another_source_keeps_its_feed_row(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session, source=f"{TEST_SOURCE_PREFIX}himalayas")
    old_key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])

    # Lost records, and meanwhile the employer's ATS posting became canonical.
    await _forget_publications(db_session, job.id)
    job.source, job.source_job_id = FETCHED, "ats-" + job.source_job_id
    job.source_url = "https://boards.greenhouse.io/pubtest/jobs/ats"
    db_session.add(JobAltSource(job_id=job.id, source=old_key[0], source_job_id=old_key[1], source_url="https://x"))
    await db_session.flush()

    summary = await run_publish(db_session, feed_engine, job_ids=[job.id])
    assert summary.reconciled.adopted == 1 and summary.results == {"UPDATED": 1}
    assert (await _feed_row(feed_admin, *old_key))["job_url"] == "https://boards.greenhouse.io/pubtest/jobs/ats"
    assert await _feed_row(feed_admin, job.source, job.source_job_id) is None  # no second live row


async def test_same_opening_found_by_company_and_title(db_session, feed_engine, feed_admin):
    job = await _add_job(db_session, source=f"{TEST_SOURCE_PREFIX}himalayas")
    old_key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    await _forget_publications(db_session, job.id)
    job.source, job.source_job_id = FETCHED, "other-id"  # no alternate-source record this time
    await db_session.flush()

    summary = await reconcile(db_session, feed_engine, datetime.now(UTC), {old_key[0], FETCHED})
    assert summary.adopted == 1
    pub = await db_session.get(FeedPublication, job.id)
    assert (pub.feed_source, pub.feed_source_job_id) == old_key


async def test_manual_job_is_reimported_from_the_feed(db_session, feed_engine, feed_admin):
    source = f"{TEST_SOURCE_PREFIX}linkedin"
    submitted = await ingest_submission(
        db_session,
        JobSubmission(
            source_url="https://www.linkedin.com/jobs/view/424242", company_name="Pubtest Robotics",
            job_title="Senior Backend Engineer", raw_job_description=_JD, source=source,
            original_location="Remote - US",
        ),
    )
    job = await db_session.get(Job, submitted.job_id)
    feed_key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    await _delete_job(db_session, job)  # platform copy gone entirely

    summary = await reconcile(db_session, feed_engine, datetime.now(UTC), {source})
    assert (summary.reimported, summary.adopted, summary.orphans_waiting) == (1, 1, 0)
    restored = (
        await db_session.execute(select(Job).where(Job.source == feed_key[0], Job.source_job_id == feed_key[1]))
    ).scalar_one()
    assert (await db_session.get(FeedPublication, restored.id)).feed_status == "ACTIVE"


async def test_unmatched_row_is_closed_only_after_a_full_fetch_cycle(db_session, feed_engine, feed_admin):
    db_session.add(Source(name=FETCHED, kind="ats", fetch_interval_seconds=10800, enabled=True, config={}))
    job = await _add_job(db_session)
    key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])
    await _delete_job(db_session, job)
    keeper = await _add_job(db_session, company_name="Other Co")  # the platform isn't empty

    waiting = await reconcile(db_session, feed_engine, datetime.now(UTC), {FETCHED})
    assert (waiting.orphans_waiting, waiting.orphans_closed) == (1, 0)
    assert (await _feed_row(feed_admin, *key))["status"] == "ACTIVE"  # may still be live: not re-fetched yet

    await _mark_every_source_fetched(db_session)
    closed = await reconcile(db_session, feed_engine, datetime.now(UTC), {FETCHED})
    assert closed.orphans_closed == 1
    assert (await _feed_row(feed_admin, *key))["status"] == "CLOSED"
    log = (
        await db_session.execute(select(FeedPublishLog).where(FeedPublishLog.feed_source_job_id == key[1]))
    ).scalar_one()
    assert (log.job_id, log.result) == (None, "ORPHAN_CLOSED")
    assert keeper.active


async def test_duplicate_feed_row_for_an_already_published_job_is_closed(db_session, feed_engine, feed_admin):
    db_session.add(Source(name=FETCHED, kind="ats", fetch_interval_seconds=10800, enabled=True, config={}))
    job = await _add_job(db_session)
    first_key = (job.source, job.source_job_id)
    await run_publish(db_session, feed_engine, job_ids=[job.id])

    # A second live row for the same job, under the key the job has now.
    await _forget_publications(db_session, job.id)
    job.source_job_id = "dup-" + job.source_job_id
    await db_session.flush()
    await run_publish(db_session, feed_engine, job_ids=[job.id])  # re-links to first_key, no new row yet
    pub = await db_session.get(FeedPublication, job.id)
    assert (pub.feed_source, pub.feed_source_job_id) == first_key

    await _mark_every_source_fetched(db_session)
    async with feed_admin.begin() as conn:  # simulate the stray duplicate that loss could have caused
        from sqlalchemy import text
        await conn.execute(
            text(
                "INSERT INTO job_feed.jobs (source, source_job_id, job_url, jd_text, company, title, verified_at, status)"
                " VALUES (:s, :i, 'https://x.example/j', 'Full text.', 'Pubtest Robotics', 'Senior Backend Engineer', now(), 'ACTIVE')"
            ),
            {"s": job.source, "i": job.source_job_id},
        )
    summary = await reconcile(db_session, feed_engine, datetime.now(UTC), {FETCHED})
    assert summary.orphans_closed == 1
    assert (await _feed_row(feed_admin, job.source, job.source_job_id))["status"] == "CLOSED"
    assert (await _feed_row(feed_admin, *first_key))["status"] == "ACTIVE"
