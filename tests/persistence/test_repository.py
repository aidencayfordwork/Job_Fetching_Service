from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.connectors.ats_common import AtsTarget
from app.connectors.base import JobDraft
from app.db.models import AtsCompany, Job, JobAltSource, Source, SourceRun
from app.persistence import repository


def _draft(**overrides) -> JobDraft:
    defaults = dict(
        source="greenhouse", source_job_id="1", company_name="Acme",
        job_title="Senior Backend Engineer", source_url="https://x/1",
        direct_apply_url="https://x/1", remote_scope="US",
        canonical_fingerprint="fp-1",
    )
    defaults.update(overrides)
    return JobDraft(**defaults)


async def test_upsert_inserts_new_job(db_session):
    row, is_new = await repository.upsert_job(db_session, _draft(), dedupe_candidates=[])
    assert is_new is True
    assert row.id is not None
    assert row.company_name == "Acme"
    assert row.active is True


async def test_upsert_same_source_job_id_updates_in_place(db_session):
    row1, _ = await repository.upsert_job(db_session, _draft(job_title="Backend Engineer"), [])
    row2, is_new = await repository.upsert_job(
        db_session, _draft(job_title="Backend Engineer, Updated"), []
    )
    assert is_new is False
    assert row1.id == row2.id
    assert row2.job_title == "Backend Engineer, Updated"

    # Scoped to this test's own (source, source_job_id), not a total table
    # count - the DB may already hold unrelated rows from outside this
    # test (other suites, manual runs against the same dev database).
    matching = (
        await db_session.execute(
            select(Job).where(Job.source == "greenhouse", Job.source_job_id == "1")
        )
    ).scalars().all()
    assert len(matching) == 1


async def test_upsert_cross_source_duplicate_recorded_as_alt_source(db_session):
    canonical, _ = await repository.upsert_job(
        db_session, _draft(source="remoteok", source_job_id="rok-1", canonical_fingerprint="fp-dup"), []
    )
    candidates = await repository.get_recent_active_jobs(db_session)

    dup_row, is_new = await repository.upsert_job(
        db_session,
        _draft(source="jobicy", source_job_id="job-1", canonical_fingerprint="fp-dup"),
        candidates,
    )
    assert is_new is False
    assert dup_row.id == canonical.id
    assert dup_row.source == "remoteok"  # remoteok and jobicy have equal priority, first stays canonical

    alt_sources = (
        await db_session.execute(select(JobAltSource).where(JobAltSource.job_id == canonical.id))
    ).scalars().all()
    assert len(alt_sources) == 1
    assert alt_sources[0].source == "jobicy"


async def test_upsert_higher_priority_source_promotes_and_demotes_old_one(db_session):
    canonical, _ = await repository.upsert_job(
        db_session,
        _draft(source="remoteok", source_job_id="rok-1", canonical_fingerprint="fp-promo"),
        [],
    )
    candidates = await repository.get_recent_active_jobs(db_session)

    promoted_row, is_new = await repository.upsert_job(
        db_session,
        _draft(source="greenhouse", source_job_id="gh-1", canonical_fingerprint="fp-promo"),
        candidates,
    )
    assert is_new is False
    assert promoted_row.id == canonical.id
    assert promoted_row.source == "greenhouse"  # promoted: ATS outranks aggregator

    alt_sources = (
        await db_session.execute(select(JobAltSource).where(JobAltSource.job_id == promoted_row.id))
    ).scalars().all()
    assert len(alt_sources) == 1
    assert alt_sources[0].source == "remoteok"  # old canonical demoted to alt source


async def test_mark_expired_jobs_deactivates_stale_rows(db_session):
    row, _ = await repository.upsert_job(db_session, _draft(), [])
    row.last_seen_at = datetime.now(UTC) - timedelta(days=10)
    await db_session.flush()

    updated = await repository.mark_expired_jobs(db_session, grace_days=5)
    assert updated == 1

    await db_session.refresh(row)
    assert row.active is False


async def test_mark_expired_jobs_leaves_recent_rows_active(db_session):
    row, _ = await repository.upsert_job(db_session, _draft(), [])
    updated = await repository.mark_expired_jobs(db_session, grace_days=5)
    assert updated == 0
    await db_session.refresh(row)
    assert row.active is True


async def test_get_enabled_ats_companies_filters_by_platform_and_enabled(db_session):
    db_session.add_all(
        [
            AtsCompany(company_name="Acme", ats_platform="greenhouse", board_token="acme", enabled=True),
            AtsCompany(company_name="Globex", ats_platform="greenhouse", board_token="globex", enabled=False),
            AtsCompany(company_name="Initech", ats_platform="lever", board_token="initech", enabled=True),
        ]
    )
    await db_session.flush()

    targets = await repository.get_enabled_ats_companies(db_session, "greenhouse")
    # Contains, not equals - the dev DB may already hold other enabled
    # greenhouse companies outside this test.
    assert AtsTarget(company_name="Acme", board_token="acme") in targets
    assert not any(t.board_token == "globex" for t in targets)


async def test_source_run_lifecycle(db_session):
    source = Source(name="test-source-xyz", kind="ats", fetch_interval_seconds=10800, enabled=True, config={})
    db_session.add(source)
    await db_session.flush()

    run = await repository.start_source_run(db_session, source.id)
    assert run.status == "running"

    await repository.finish_source_run(
        db_session, run, status="success", jobs_fetched=10, jobs_new=3,
        jobs_updated=2, jobs_filtered_out=5,
    )
    assert run.status == "success"
    assert run.finished_at is not None
    assert run.duration_ms is not None

    fetched = (await db_session.execute(select(SourceRun).where(SourceRun.id == run.id))).scalar_one()
    assert fetched.jobs_new == 3
