"""Adzuna connector tests against a mocked response matching the
documented API format (this project has no real app_id/app_key to test
against the live API - see adzuna.py's module docstring)."""

from types import SimpleNamespace

import respx
from httpx import Response

from app.connectors.adzuna import AdzunaConnector


def _fake_settings(**overrides):
    base = dict(adzuna_app_id="test-id", adzuna_app_key="test-key")
    base.update(overrides)
    return SimpleNamespace(**base)


@respx.mock
async def test_fetch_returns_nothing_without_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.adzuna.get_settings",
        lambda: _fake_settings(adzuna_app_id="", adzuna_app_key=""),
    )
    connector = AdzunaConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert raws == []


@respx.mock
async def test_fetch_and_normalize(monkeypatch):
    monkeypatch.setattr("app.connectors.adzuna.get_settings", _fake_settings)

    payload = {
        "results": [
            {
                "id": "12345",
                "title": "Senior Backend Engineer",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Remote, US"},
                "category": {"label": "IT Jobs"},
                "description": "Build APIs in Python on AWS.",
                "created": "2026-09-01T10:00:00Z",
                "salary_min": 150000,
                "salary_max": 180000,
                "salary_is_predicted": "0",
                "contract_time": "full_time",
                "redirect_url": "https://adzuna.com/land/ad/12345",
            }
        ]
    }
    respx.get("https://api.adzuna.com/v1/api/jobs/us/search/1").mock(return_value=Response(200, json=payload))
    # Only one page returned (fewer than _RESULTS_PER_PAGE), so the loop
    # should stop without requesting page 2.

    connector = AdzunaConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    assert len(raws) == 1

    draft = connector.normalize(raws[0])
    assert draft.company_name == "Acme"
    assert draft.job_title == "Senior Backend Engineer"
    assert draft.original_location == "Remote, US"
    assert draft.employment_type == "full_time"
    assert draft.salary_min == 150000
    assert draft.salary_max == 180000
    assert draft.direct_apply_url == "https://adzuna.com/land/ad/12345"


@respx.mock
async def test_predicted_salary_is_treated_as_unknown(monkeypatch):
    monkeypatch.setattr("app.connectors.adzuna.get_settings", _fake_settings)

    payload = {
        "results": [
            {
                "id": "999",
                "title": "Backend Engineer",
                "company": {"display_name": "Acme"},
                "salary_min": 100000,
                "salary_max": 120000,
                "salary_is_predicted": "1",
                "redirect_url": "https://adzuna.com/land/ad/999",
            }
        ]
    }
    respx.get("https://api.adzuna.com/v1/api/jobs/us/search/1").mock(return_value=Response(200, json=payload))

    connector = AdzunaConnector()
    raws = [raw async for raw in connector.fetch(since=None)]
    draft = connector.normalize(raws[0])
    assert draft.salary_min is None
    assert draft.salary_max is None
