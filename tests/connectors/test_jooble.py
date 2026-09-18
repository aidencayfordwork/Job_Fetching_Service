"""Jooble connector tests against a mocked response matching the
documented API format (this project has no real API key to test against
the live API - see jooble.py's module docstring)."""

from types import SimpleNamespace

import respx
from httpx import Response

from app.connectors.jooble import JoobleConnector


def _fake_settings(**overrides):
    base = dict(jooble_api_key="test-key")
    base.update(overrides)
    return SimpleNamespace(**base)


@respx.mock
async def test_fetch_returns_nothing_without_credentials(monkeypatch):
    monkeypatch.setattr("app.connectors.jooble.get_settings", lambda: _fake_settings(jooble_api_key=""))
    connector = JoobleConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert raws == []


@respx.mock
async def test_fetch_and_normalize(monkeypatch):
    monkeypatch.setattr("app.connectors.jooble.get_settings", _fake_settings)

    payload = {
        "totalCount": 1,
        "jobs": [
            {
                "id": 777,
                "title": "Backend Engineer",
                "company": "Acme",
                "location": "United States",
                "snippet": "Build APIs in Python.",
                "salary": "$140,000 - $170,000",
                "source": "acme.com",
                "type": "Full-time",
                "link": "https://jooble.org/desc/777",
                "updated": "2026-09-01T10:00:00Z",
            }
        ],
    }
    respx.post("https://jooble.org/api/test-key").mock(return_value=Response(200, json=payload))

    connector = JoobleConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Backend Engineer"
    assert draft.original_location == "United States"
    assert draft.employment_type == "full_time"
    assert draft.salary_min == 140000
    assert draft.salary_max == 170000
    assert draft.source_url == "https://jooble.org/desc/777"
