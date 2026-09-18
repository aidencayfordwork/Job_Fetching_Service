from app.db.models import Source, SourceRun
from app.scheduler.health import get_source_health


async def test_health_unknown_source_returns_none(db_session):
    health = await get_source_health(db_session, "does-not-exist")
    assert health is None


async def test_health_no_runs_yet(db_session):
    source = Source(name="test-src-a", kind="ats", fetch_interval_seconds=10800, enabled=True, config={})
    db_session.add(source)
    await db_session.flush()

    health = await get_source_health(db_session, "test-src-a")
    assert health is not None
    assert health.last_fetch_at is None
    assert health.last_status is None
    assert health.consecutive_failures == 0


async def test_health_reflects_last_run_and_consecutive_failures(db_session):
    source = Source(name="test-src-b", kind="ats", fetch_interval_seconds=10800, enabled=True, config={})
    db_session.add(source)
    await db_session.flush()

    db_session.add_all(
        [
            SourceRun(source_id=source.id, status="success", jobs_fetched=5, jobs_new=2, jobs_updated=1, jobs_filtered_out=2),
            SourceRun(source_id=source.id, status="failed", jobs_fetched=0, jobs_new=0, jobs_updated=0, jobs_filtered_out=0, error_message="boom"),
            SourceRun(source_id=source.id, status="failed", jobs_fetched=0, jobs_new=0, jobs_updated=0, jobs_filtered_out=0, error_message="boom again"),
        ]
    )
    await db_session.flush()

    health = await get_source_health(db_session, "test-src-b")
    assert health.last_status == "failed"
    assert health.consecutive_failures == 2
    assert health.errors_last_run == "boom again"
