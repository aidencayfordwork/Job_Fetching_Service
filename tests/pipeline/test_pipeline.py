from app.connectors.base import JobDraft
from app.pipeline.dedupe import ExistingJobRef, compute_fingerprint
from app.pipeline.pipeline import process_job


def _draft(**overrides) -> JobDraft:
    defaults = dict(
        source="greenhouse", source_job_id="1", company_name="Acme",
        job_title="Senior Backend Engineer", source_url="https://x",
        original_location="Remote - US",
        cleaned_job_description="Build APIs in Python and Go on AWS.",
    )
    defaults.update(overrides)
    return JobDraft(**defaults)


def test_full_pipeline_keeps_and_classifies_valid_job():
    result = process_job(_draft())

    assert result.kept is True
    assert result.reason is None
    assert result.job.level == "SENIOR"
    assert result.job.role_category == "Backend"
    assert "Python" in result.job.full_technology_stack
    assert "Python" in result.job.matched_keywords
    assert result.job.us_eligible is True
    assert result.duplicate_of is None


def test_full_pipeline_excludes_and_stops_before_keywords():
    result = process_job(_draft(job_title="Software Engineering Intern"))

    assert result.kept is False
    assert result.reason == "seniority_out_of_band"
    # Excluded jobs don't pay the cost of keyword matching.
    assert result.job.matched_keywords == []


def test_full_pipeline_flags_duplicate():
    # Fingerprint as it will look AFTER classify/filter run (remote_scope
    # gets set to "US" by then) - process_job mutates its job in place, so
    # the fingerprint must be computed against that post-classification
    # shape, not the fresh draft.
    fingerprint_after_classification = compute_fingerprint(_draft(remote_scope="US"))
    existing = ExistingJobRef(
        id=42, source="remoteok", source_job_id="999", company_name="Acme",
        job_title="Senior Backend Engineer", canonical_fingerprint=fingerprint_after_classification,
    )

    result = process_job(_draft(), dedupe_candidates=[existing])

    assert result.kept is True
    assert result.duplicate_of is existing
