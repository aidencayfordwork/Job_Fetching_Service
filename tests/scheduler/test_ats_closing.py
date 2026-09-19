"""ATS jobs close after 2 consecutive complete board fetches that no longer
list them - not only after the 5-day unseen grace period."""

from datetime import UTC, datetime, timedelta

import respx
from httpx import Response
from sqlalchemy import select

from app.connectors.greenhouse import GreenhouseConnector
from app.db.models import AtsCompany, Job, Source
from app.scheduler.runner import run_source

_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/closeco/jobs"
_RECENT = (datetime.now(UTC) - timedelta(days=1)).isoformat()


_TITLES = {9102: "Senior Platform Engineer"}


def _posting(job_id: int) -> dict:
    return {
        "id": job_id,
        # Distinct titles, or cross-job dedup would merge them into one job.
        "title": _TITLES.get(job_id, "Senior Backend Engineer"),
        "company_name": "Close Co",
        "absolute_url": f"https://boards.greenhouse.io/closeco/jobs/{job_id}",
        "location": {"name": "Remote - US"},
        "content": "&lt;p&gt;Build Python services on AWS. Fully remote in the United States.&lt;/p&gt;",
        "updated_at": _RECENT,
        "first_published": _RECENT,
    }


async def _setup(db_session) -> GreenhouseConnector:
    db_session.add(Source(name="close-test-gh", kind="ats", fetch_interval_seconds=10800, enabled=True, config={}))
    db_session.add(
        AtsCompany(
            company_name="Close Co", ats_platform="close-test-gh", board_token="closeco",
            source_of_discovery="manual", verified=True, enabled=True,
        )
    )
    await db_session.flush()
    connector = GreenhouseConnector()
    connector.name = "close-test-gh"
    return connector


async def _job(db_session, job_id: int) -> Job:
    db_session.expire_all()
    return (
        await db_session.execute(select(Job).where(Job.source == "close-test-gh", Job.source_job_id == str(job_id)))
    ).scalar_one()


@respx.mock
async def test_job_missing_from_two_complete_fetches_is_closed(db_session):
    connector = await _setup(db_session)
    route = respx.get(_BOARD_URL)

    route.mock(return_value=Response(200, json={"jobs": [_posting(9101), _posting(9102)]}))
    await run_source(connector, session=db_session)
    assert (await _job(db_session, 9101)).active
    gone = await _job(db_session, 9102)
    assert gone.active and gone.ats_board_token == "closeco"

    route.mock(return_value=Response(200, json={"jobs": [_posting(9101)]}))
    await run_source(connector, session=db_session)
    gone = await _job(db_session, 9102)
    assert gone.active and gone.consecutive_misses == 1  # one miss isn't enough

    await run_source(connector, session=db_session)
    assert not (await _job(db_session, 9102)).active
    kept = await _job(db_session, 9101)
    assert kept.active and kept.consecutive_misses == 0


@respx.mock
async def test_reappearing_job_resets_its_misses(db_session):
    connector = await _setup(db_session)
    route = respx.get(_BOARD_URL)
    route.mock(return_value=Response(200, json={"jobs": [_posting(9201)]}))
    await run_source(connector, session=db_session)
    route.mock(return_value=Response(200, json={"jobs": []}))
    await run_source(connector, session=db_session)
    assert (await _job(db_session, 9201)).consecutive_misses == 1

    route.mock(return_value=Response(200, json={"jobs": [_posting(9201)]}))
    await run_source(connector, session=db_session)
    job = await _job(db_session, 9201)
    assert job.active and job.consecutive_misses == 0


@respx.mock
async def test_board_that_fails_to_load_never_counts_as_a_miss(db_session):
    connector = await _setup(db_session)
    route = respx.get(_BOARD_URL)
    route.mock(return_value=Response(200, json={"jobs": [_posting(9301)]}))
    await run_source(connector, session=db_session)

    route.mock(return_value=Response(404))
    await run_source(connector, session=db_session)
    await run_source(connector, session=db_session)
    job = await _job(db_session, 9301)
    assert job.active and job.consecutive_misses == 0


@respx.mock
async def test_board_with_an_unparseable_job_never_counts_as_a_miss(db_session):
    connector = await _setup(db_session)
    route = respx.get(_BOARD_URL)
    route.mock(return_value=Response(200, json={"jobs": [_posting(9401)]}))
    await run_source(connector, session=db_session)

    broken = {"id": 9402}  # missing every field normalize() needs
    route.mock(return_value=Response(200, json={"jobs": [broken]}))
    await run_source(connector, session=db_session)
    await run_source(connector, session=db_session)
    assert (await _job(db_session, 9401)).active
