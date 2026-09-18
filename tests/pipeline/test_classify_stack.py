from app.connectors.base import JobDraft
from app.pipeline.classify_stack import classify_stack


def _job(title: str, jd: str = "", existing_stack: list[str] | None = None) -> JobDraft:
    job = JobDraft(
        source="test", source_job_id="1", company_name="Acme",
        job_title=title, source_url="https://x", cleaned_job_description=jd,
    )
    if existing_stack:
        job.full_technology_stack = existing_stack
    return job


def test_extracts_languages_and_infra():
    job = classify_stack(_job(
        "Senior Backend Engineer",
        "We build services in Python and Go on AWS using Kubernetes and PostgreSQL.",
    ))
    for tech in ("Python", "Go", "AWS", "Kubernetes", "PostgreSQL"):
        assert tech in job.full_technology_stack
    assert len(job.main_stack) <= 4
    assert set(job.main_stack).issubset(set(job.full_technology_stack))


def test_excludes_non_tech_categories_like_domains():
    job = classify_stack(_job("Backend Engineer", "We follow Agile and value distributed systems thinking."))
    assert "Agile" not in job.full_technology_stack
    assert "Distributed Systems" not in job.full_technology_stack


def test_preserves_source_provided_stack():
    job = classify_stack(_job("Backend Engineer", "", existing_stack=["rust", "wasm"]))
    assert "rust" in job.full_technology_stack
    assert "wasm" in job.full_technology_stack


def test_no_tech_mentions_results_in_empty_stack():
    job = classify_stack(_job("Product Manager", "You'll own the roadmap and talk to customers."))
    assert job.full_technology_stack == []
    assert job.main_stack == []
