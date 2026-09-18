from app.pipeline.normalize import clean_html, parse_salary


def test_clean_html_strips_tags_and_unescapes():
    raw = "&lt;p&gt;Hello &amp; welcome.&lt;/p&gt;&lt;br/&gt;Next line."
    cleaned = clean_html(raw)
    assert "<" not in cleaned and "&lt;" not in cleaned
    assert "Hello & welcome." in cleaned
    assert "Next line." in cleaned


def test_clean_html_strips_spam_marker():
    raw = "<p>Great job.</p>Please mention the word BANANA when applying to show you read it."
    cleaned = clean_html(raw)
    assert "Great job." in cleaned
    assert "BANANA" not in cleaned


def test_clean_html_empty_input():
    assert clean_html(None) == ""
    assert clean_html("") == ""


def test_parse_salary_basic_range():
    guess = parse_salary("We pay $150,000 - $180,000 per year for this role.")
    assert guess.salary_min == 150000
    assert guess.salary_max == 180000
    assert guess.currency == "USD"
    assert guess.salary_period == "year"


def test_parse_salary_k_shorthand():
    guess = parse_salary("Compensation: $120k-$150k/year")
    assert guess.salary_min == 120000
    assert guess.salary_max == 150000


def test_parse_salary_no_match_returns_all_none():
    guess = parse_salary("This role has a competitive salary.")
    assert guess.salary_min is None
    assert guess.salary_max is None
    assert guess.currency is None
