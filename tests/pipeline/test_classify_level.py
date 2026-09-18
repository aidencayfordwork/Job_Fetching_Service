from app.connectors.base import JobDraft
from app.pipeline.classify_level import classify_level


def _job(title: str, jd: str = "") -> JobDraft:
    return JobDraft(
        source="test", source_job_id="1", company_name="Acme",
        job_title=title, source_url="https://x", cleaned_job_description=jd,
    )


def test_senior_title():
    assert classify_level(_job("Senior Backend Engineer")).level == "SENIOR"


def test_staff_title():
    assert classify_level(_job("Staff Software Engineer")).level == "STAFF"


def test_lead_title():
    assert classify_level(_job("Lead Platform Engineer")).level == "LEAD"
    assert classify_level(_job("Tech Lead, Data Infrastructure")).level == "LEAD"


def test_mid_level_explicit_title():
    assert classify_level(_job("Mid-Level Frontend Engineer")).level == "MID"


def test_senior_principal_is_excluded_principal_wins():
    assert classify_level(_job("Senior Principal Engineer")).level is None


def test_excludes_junior_intern_new_grad_director():
    assert classify_level(_job("Junior Software Engineer")).level is None
    assert classify_level(_job("Software Engineering Intern")).level is None
    assert classify_level(_job("New Grad Software Engineer")).level is None
    assert classify_level(_job("Director of Engineering")).level is None
    assert classify_level(_job("Distinguished Engineer")).level is None


def test_jd_years_fallback_when_title_ambiguous():
    job = classify_level(_job("Backend Engineer", "You have 6 years of experience building APIs."))
    assert job.level == "SENIOR"
    assert job.required_years_experience == 6


def test_jd_years_too_junior_excludes():
    job = classify_level(_job("Backend Engineer", "You have 1 year of experience."))
    assert job.level is None


def test_jd_exclusion_marker_near_top_excludes():
    job = classify_level(_job("Backend Engineer", "This is an entry-level position for recent graduates."))
    assert job.level is None


def test_no_signal_defaults_to_mid():
    job = classify_level(_job("Software Engineer", "We build cool things with modern tools."))
    assert job.level == "MID"
