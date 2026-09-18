import respx
from httpx import Response
from sqlalchemy import select

from app.db.models import AtsCompany, Job
from app.scheduler.discovery_job import run_discovery


def _job_row(company_name: str, source_job_id: str) -> Job:
    return Job(
        company_name=company_name, job_title="Senior Backend Engineer",
        source="remoteok", source_job_id=source_job_id, source_url="https://x",
        canonical_fingerprint=f"fp-{source_job_id}", active=True,
    )


@respx.mock
async def test_discovery_finds_and_persists_organic_company(db_session):
    db_session.add(_job_row("Acme", "1"))
    await db_session.flush()

    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=Response(200, json={"jobs": []})
    )
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=Response(404))
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(return_value=Response(404))
    respx.route(host__regex=".*").mock(return_value=Response(404))

    # A generous limit so "Acme" is reliably included in the SQL-level
    # LIMIT even if the dev DB already has other distinct company names
    # from outside this test (e.g. a manual end-to-end run) - all
    # candidate probes are respx-mocked, so a larger limit costs nothing.
    await run_discovery(candidate_limit=1000, session=db_session)

    rows = (
        await db_session.execute(select(AtsCompany).where(AtsCompany.company_name == "Acme"))
    ).scalars().all()
    assert any(r.ats_platform == "greenhouse" for r in rows)
    assert all(r.source_of_discovery == "organic" for r in rows)


@respx.mock
async def test_discovery_skips_already_known_companies(db_session):
    db_session.add(_job_row("Acme", "1"))
    db_session.add(
        AtsCompany(
            company_name="Acme", ats_platform="greenhouse", board_token="acme",
            source_of_discovery="manual", verified=True, enabled=True,
        )
    )
    await db_session.flush()

    respx.route(host__regex=".*").mock(return_value=Response(404))

    await run_discovery(candidate_limit=1000, session=db_session)

    rows = (
        await db_session.execute(select(AtsCompany).where(AtsCompany.company_name == "Acme"))
    ).scalars().all()
    assert len(rows) == 1  # untouched, no duplicate probe/insert for a known company
    assert rows[0].source_of_discovery == "manual"
