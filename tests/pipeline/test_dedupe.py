from app.connectors.base import JobDraft
from app.pipeline.dedupe import (
    ExistingJobRef,
    compute_fingerprint,
    find_duplicate,
    is_higher_priority_source,
    normalize_company_name,
)


def _job(**overrides) -> JobDraft:
    defaults = dict(
        source="remoteok", source_job_id="1", company_name="Acme Inc.",
        job_title="Senior Backend Engineer", source_url="https://x",
        remote_scope="US",
    )
    defaults.update(overrides)
    return JobDraft(**defaults)


def test_normalize_company_name_strips_suffix_and_punctuation():
    assert normalize_company_name("Acme, Inc.") == "acme"
    assert normalize_company_name("Acme LLC") == "acme"
    assert normalize_company_name("Acme") == "acme"


def test_fingerprint_stable_across_equivalent_company_spelling():
    job_a = _job(company_name="Acme Inc.")
    job_b = _job(company_name="Acme")
    assert compute_fingerprint(job_a) == compute_fingerprint(job_b)


def test_fingerprint_differs_for_different_titles():
    job_a = _job(job_title="Senior Backend Engineer")
    job_b = _job(job_title="Senior Frontend Engineer")
    assert compute_fingerprint(job_a) != compute_fingerprint(job_b)


def test_find_duplicate_exact_fingerprint_match():
    job = _job()
    existing = ExistingJobRef(
        id=1, source="greenhouse", source_job_id="99", company_name="Acme",
        job_title="Senior Backend Engineer", canonical_fingerprint=compute_fingerprint(job),
    )
    assert find_duplicate(job, [existing]) is existing


def test_find_duplicate_fuzzy_title_match_same_company():
    job = _job(job_title="Senior Backend Engineer (Remote)")
    existing = ExistingJobRef(
        id=1, source="greenhouse", source_job_id="99", company_name="Acme Inc.",
        job_title="Senior Backend Engineer",
        canonical_fingerprint="different-fingerprint-entirely",
    )
    assert find_duplicate(job, [existing]) is existing


def test_find_duplicate_no_match_different_company():
    job = _job(company_name="Acme")
    existing = ExistingJobRef(
        id=1, source="greenhouse", source_job_id="99", company_name="Globex",
        job_title="Senior Backend Engineer", canonical_fingerprint="whatever",
    )
    assert find_duplicate(job, [existing]) is None


def test_find_duplicate_no_match_different_role_same_company():
    job = _job(job_title="Senior Backend Engineer")
    existing = ExistingJobRef(
        id=1, source="greenhouse", source_job_id="99", company_name="Acme",
        job_title="Senior Recruiter", canonical_fingerprint="whatever",
    )
    assert find_duplicate(job, [existing]) is None


def test_find_duplicate_empty_candidates_returns_none():
    assert find_duplicate(_job(), []) is None


def test_source_priority_ats_beats_aggregator():
    assert is_higher_priority_source("greenhouse", "remoteok") is True
    assert is_higher_priority_source("remoteok", "greenhouse") is False


def test_source_priority_equal_sources_neither_wins():
    assert is_higher_priority_source("remoteok", "remotive") is False
