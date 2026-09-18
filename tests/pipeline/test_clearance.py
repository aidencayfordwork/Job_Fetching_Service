from app.pipeline.clearance import requires_active_clearance


def test_active_secret_clearance_flagged():
    assert requires_active_clearance("Candidates must have an active Secret clearance.") is True


def test_current_ts_sci_flagged():
    assert requires_active_clearance("Must currently hold TS/SCI clearance.") is True


def test_active_top_secret_flagged():
    assert requires_active_clearance("Requires an active Top Secret clearance.") is True


def test_ability_to_obtain_not_flagged():
    assert requires_active_clearance("Ability to obtain a security clearance is required.") is False


def test_eligible_to_obtain_not_flagged():
    assert requires_active_clearance("Must be eligible to obtain a security clearance.") is False


def test_public_trust_not_flagged():
    assert requires_active_clearance("This role requires Public Trust clearance eligibility.") is False


def test_background_check_not_flagged():
    assert requires_active_clearance("All candidates must pass a background check.") is False


def test_citizenship_required_not_flagged():
    assert requires_active_clearance("US citizenship is required for this role.") is False


def test_no_mention_not_flagged():
    assert requires_active_clearance("We build great software together.") is False


def test_none_input_not_flagged():
    assert requires_active_clearance(None) is False
