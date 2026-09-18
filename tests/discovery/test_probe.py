import respx
from httpx import Response

from app.discovery.probe import ProbeHit, candidate_slugs, probe_company


def test_candidate_slugs_basic():
    assert candidate_slugs("Airbnb") == ["airbnb"]


def test_candidate_slugs_strips_suffix_and_punctuation():
    slugs = candidate_slugs("Notion Labs, Inc.")
    assert "notionlabs" in slugs
    assert "notion-labs" in slugs
    assert "notionlabsinc" in slugs  # unsuffixed variant kept too


def test_candidate_slugs_empty_for_blank_name():
    assert candidate_slugs("   ") == []


@respx.mock
async def test_probe_company_finds_greenhouse_match():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=Response(200, json={"jobs": []})
    )
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=Response(404))
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(return_value=Response(404))

    hits = await probe_company("Acme")
    assert hits == [ProbeHit(ats_platform="greenhouse", board_token="acme")]


@respx.mock
async def test_probe_company_no_hits_for_unknown_company():
    respx.get("https://boards-api.greenhouse.io/v1/boards/nope/jobs").mock(return_value=Response(404))
    respx.get("https://api.lever.co/v0/postings/nope").mock(return_value=Response(404))
    respx.get("https://api.ashbyhq.com/posting-api/job-board/nope").mock(return_value=Response(404))

    hits = await probe_company("Nope")
    assert hits == []
