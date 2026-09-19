from datetime import UTC, datetime, timedelta

from app.db.models import Job
from app.publish.feed_row import (
    annual_usd_salary,
    canonical_url,
    clean_title,
    display_company,
    feed_status,
    hold_back_reason,
)

_JD = "About the role\n\nYou will build Python services on AWS for our payments platform. " * 8


def _job(**overrides) -> Job:
    fields = dict(
        id=1, source="greenhouse", source_job_id="123", company_name="Acme Robotics",
        job_title="Senior Backend Engineer", source_url="https://boards.greenhouse.io/acme/jobs/123",
        original_location="Remote - US", is_remote=True, us_eligible=True, remote_scope="US",
        requires_active_clearance=False, active=True, raw_job_description=_JD,
        posted_at=datetime.now(UTC) - timedelta(days=1),
    )
    fields.update(overrides)
    return Job(**fields)


def test_clean_title_removes_only_appended_noise():
    assert clean_title("Senior Backend Engineer (Remote)") == "Senior Backend Engineer"
    assert clean_title("Senior Backend Engineer - Remote, US") == "Senior Backend Engineer"
    assert clean_title("Mobile Developer I - US Remote") == "Mobile Developer I"
    assert clean_title("Senior Software Engineer (Remote - US Based)") == "Senior Software Engineer"
    assert clean_title("Staff Engineer [R12345]") == "Staff Engineer"
    assert clean_title("Senior Backend Engineer 🚀") == "Senior Backend Engineer"
    # Real content in brackets is kept.
    assert clean_title("Senior Backend Developer (Python)") == "Senior Backend Developer (Python)"
    assert clean_title("Engineering Manager (ML)") == "Engineering Manager (ML)"


def test_canonical_url_strips_tracking_and_forces_https():
    assert (
        canonical_url("http://jobs.example.com/1?utm_source=x&gh_src=y&ref=z&gh_jid=42#apply")
        == "https://jobs.example.com/1?gh_jid=42"
    )
    assert canonical_url("mailto:jobs@example.com") is None
    assert canonical_url(None) is None


def test_salary_only_when_annual_usd():
    assert annual_usd_salary(_job(salary_min=150000, salary_max=180000, currency="USD", salary_period="year")) == (150000, 180000)
    assert annual_usd_salary(_job(salary_min=150000, salary_max=None, currency="USD", salary_period="year")) == (150000, 150000)
    # Unstated period is accepted only for figures that can only be annual.
    assert annual_usd_salary(_job(salary_min=150000, salary_max=180000, currency="USD", salary_period=None)) == (150000, 180000)
    assert annual_usd_salary(_job(salary_min=60, salary_max=80, currency="USD", salary_period="hour")) == (None, None)
    assert annual_usd_salary(_job(salary_min=90000, salary_max=120000, currency="CAD", salary_period="year")) == (None, None)
    assert annual_usd_salary(_job(salary_min=None, salary_max=None, currency="USD", salary_period="year")) == (None, None)


def test_status_active_closed_expired():
    now = datetime.now(UTC)
    assert feed_status(_job(active=True), 7, now) == "ACTIVE"
    assert feed_status(_job(active=False), 7, now) == "CLOSED"
    assert feed_status(_job(active=False, posted_at=now - timedelta(days=30)), 7, now) == "EXPIRED"


def test_hold_back_reasons():
    assert hold_back_reason(_job(), _JD) is None
    assert hold_back_reason(_job(source="adzuna"), _JD) == "description_truncated"
    assert hold_back_reason(_job(), "Short.") == "description_too_short"
    template = _JD + "\n- Begin each bullet with an action-oriented verb\n" * 3
    assert hold_back_reason(_job(), template) == "template_posting"
    assert hold_back_reason(_job(company_name="Confidential"), _JD) == "no_named_employer"
    assert hold_back_reason(_job(job_title="Security Engineer with Security Clearance"), _JD) == "requires_clearance"
    assert hold_back_reason(_job(original_location="Mexico"), _JD) == "not_verified_us_remote"
    assert hold_back_reason(_job(original_location="Remote"), _JD) == "not_verified_us_remote"
    assert hold_back_reason(_job(original_location="Remote - US", raw_job_description=_JD + " This is a hybrid role."), _JD + " This is a hybrid role.") == "not_verified_us_remote"


def test_display_company_drops_legal_suffixes_only():
    assert display_company("Chime Financial, Inc") == "Chime Financial"
    assert display_company("Stripe, Inc.") == "Stripe"
    assert display_company("Acme Robotics LLC") == "Acme Robotics"
    assert display_company("Widgets Pty Ltd") == "Widgets"
    assert display_company("  Figma  ") == "Figma"
    # Names that merely contain those letters are untouched.
    assert display_company("Incode Technologies") == "Incode Technologies"
    assert display_company("Corpay") == "Corpay"
    assert display_company("Inc") == "Inc"
