from datetime import UTC, datetime, timedelta

from app.connectors.base import JobDraft
from app.pipeline.filters import apply_filters, assess_remote_us


def _job(**overrides) -> JobDraft:
    defaults = dict(
        source="test", source_job_id="1", company_name="Acme",
        job_title="Senior Backend Engineer", source_url="https://x",
        cleaned_job_description="Build things.",
        level="SENIOR", role_category="Backend",
    )
    defaults.update(overrides)
    return JobDraft(**defaults)


def test_explicit_remote_us_location():
    job = _job(original_location="Remote - US")
    a = assess_remote_us(job)
    assert a.is_remote is True
    assert a.us_eligible is True
    assert a.remote_scope == "US"


def test_hybrid_location_not_remote():
    job = _job(original_location="New York, NY (hybrid)")
    a = assess_remote_us(job)
    assert a.is_remote is False


def test_source_provided_is_remote_overridden_by_hybrid_in_jd():
    job = _job(is_remote=True, original_location="Austin, TX", cleaned_job_description="This is a hybrid role, 3 days a week in office.")
    a = assess_remote_us(job)
    assert a.is_remote is False


def test_ashby_style_remote_non_us_region():
    # Real shape seen from Linear's Ashby board: "Europe (Remote)".
    job = _job(is_remote=True, original_location="Europe (Remote)")
    a = assess_remote_us(job)
    assert a.is_remote is True
    assert a.us_eligible is False


def test_worldwide_job_is_remote_but_not_a_us_job():
    # Owner's rule: only jobs explicitly for the US, not jobs a US engineer
    # could merely also take.
    job = _job(original_location="Anywhere in the World")
    a = assess_remote_us(job)
    assert a.is_remote is True
    assert a.us_eligible is False
    assert a.remote_scope == "Global"


def test_north_america_alone_is_ambiguous():
    # Real shape seen from Remotive: "Northern America, LATAM, Europe, APAC".
    job = _job(original_location="Northern America, LATAM, Europe, APAC")
    a = assess_remote_us(job)
    assert a.us_eligible is None


def test_explicit_exclusion_carveout():
    job = _job(original_location="Remote - Worldwide (excluding the US)")
    a = assess_remote_us(job)
    assert a.us_eligible is False


def test_state_restricted_scope():
    job = _job(original_location="Remote (CA, NY, WA only)")
    a = assess_remote_us(job)
    assert a.us_eligible is True
    assert a.remote_scope == "US-partial"
    assert "california" in a.eligible_states or "ca" in a.eligible_states


def test_apply_filters_keeps_valid_job():
    job = _job(original_location="Remote - US")
    outcome = apply_filters(job)
    assert outcome.kept is True
    assert outcome.reason is None


def test_apply_filters_excludes_active_clearance():
    job = _job(
        original_location="Remote - US",
        cleaned_job_description="Must have an active Secret clearance.",
    )
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "requires_active_clearance"


def test_apply_filters_excludes_non_remote():
    job = _job(original_location="New York, NY (hybrid)")
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "not_confirmed_remote"


def test_apply_filters_excludes_non_us():
    job = _job(original_location="Remote - UK only")
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "not_confirmed_us_eligible"


def test_apply_filters_excludes_non_target_role():
    job = _job(original_location="Remote - US", role_category=None)
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "not_a_target_role"


def test_apply_filters_excludes_bad_seniority():
    job = _job(original_location="Remote - US", level=None)
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "seniority_out_of_band"


def test_apply_filters_excludes_job_posted_over_a_week_ago():
    job = _job(original_location="Remote - US", posted_at=datetime.now(UTC) - timedelta(days=10))
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "posted_too_long_ago"


def test_apply_filters_keeps_job_posted_within_a_week():
    job = _job(original_location="Remote - US", posted_at=datetime.now(UTC) - timedelta(days=3))
    outcome = apply_filters(job)
    assert outcome.kept is True


def test_apply_filters_keeps_job_with_unknown_posted_at():
    job = _job(original_location="Remote - US", posted_at=None)
    outcome = apply_filters(job)
    assert outcome.kept is True


def test_apply_filters_handles_naive_posted_at_without_crashing():
    # A connector bug could theoretically produce a naive datetime - this
    # must not crash the whole job, just treat it as if it were UTC.
    naive_old = datetime.now() - timedelta(days=10)
    job = _job(original_location="Remote - US", posted_at=naive_old)
    outcome = apply_filters(job)
    assert outcome.kept is False
    assert outcome.reason == "posted_too_long_ago"


def test_non_us_location_field_is_not_overridden_by_a_us_mention_in_the_description():
    # Real case: location "Japan", JD mentioned the US-based parent company.
    job = _job(original_location="Japan", cleaned_job_description="Join our U.S.-based team as we expand.")
    assert assess_remote_us(job).us_eligible is False


def test_marketing_use_of_global_is_not_worldwide_remote():
    # Real cases: locations "Mexico", "Germany", "Portugal" were read as worldwide
    # because the description said "a global company".
    for location in ("Mexico", "Germany", "Portugal", "Dublin, Ireland", "Brazil,  Mexico"):
        job = _job(original_location=location, cleaned_job_description="We are a global company. Fully remote.")
        assert assess_remote_us(job).us_eligible is False, location
    job = _job(original_location="Remote", cleaned_job_description="We are a global company. Fully remote.")
    assert assess_remote_us(job).us_eligible is None


def test_worldwide_jobs_are_excluded_with_their_own_reason():
    for location in ("Remote - Global", "Anywhere in the World", "Anywhere", "Worldwide"):
        a = assess_remote_us(_job(original_location=location))
        assert (a.us_eligible, a.remote_scope) == (False, "Global"), location
    job = _job(original_location="Remote", cleaned_job_description="Fully remote - work from anywhere.")
    assert assess_remote_us(job).us_eligible is False
    outcome = apply_filters(_job(original_location="Anywhere in the World", posted_at=datetime.now(UTC)))
    assert (outcome.kept, outcome.reason) == (False, "worldwide_not_us_specific")


def test_us_named_alongside_other_countries_still_counts():
    assert assess_remote_us(_job(original_location="Remote - US or Canada")).us_eligible is True


def test_us_listed_among_other_countries_is_eligible():
    assert assess_remote_us(_job(original_location="United Kingdom, United States")).us_eligible is True


def test_must_be_based_abroad_in_description_excludes():
    job = _job(original_location="Remote", cleaned_job_description="Remote role. You must be based in Brazil.")
    assert assess_remote_us(job).us_eligible is False


def test_new_mexico_is_a_us_state_not_mexico():
    assert assess_remote_us(_job(original_location="Albuquerque, New Mexico")).remote_scope == "US-partial"


def test_dotted_us_abbreviation_followed_by_a_space_is_a_us_signal():
    a = assess_remote_us(_job(original_location="U.S. Remote"))
    assert (a.us_eligible, a.remote_scope) == (True, "US")
    assert assess_remote_us(_job(original_location="Remote", cleaned_job_description="Not available in the U.S. at this time.")).us_eligible is False
