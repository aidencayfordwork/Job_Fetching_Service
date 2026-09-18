from app.connectors.base import JobDraft
from app.pipeline.classify_role import classify_role


def _job(title: str, jd: str = "") -> JobDraft:
    return JobDraft(
        source="test", source_job_id="1", company_name="Acme",
        job_title=title, source_url="https://x", cleaned_job_description=jd,
    )


def test_ai_genai_title():
    assert classify_role(_job("Senior Generative AI Engineer")).role_category == "AI / Generative AI"


def test_machine_learning_title():
    assert classify_role(_job("Machine Learning Engineer")).role_category == "Machine Learning"


def test_devops_sre_title():
    assert classify_role(_job("Senior Site Reliability Engineer")).role_category == "DevOps / SRE"
    assert classify_role(_job("DevOps Engineer")).role_category == "DevOps / SRE"


def test_mobile_title():
    assert classify_role(_job("Senior iOS Engineer")).role_category == "Mobile / Android / iOS"


def test_backend_frontend_fullstack():
    assert classify_role(_job("Senior Backend Engineer")).role_category == "Backend"
    assert classify_role(_job("Senior Frontend Engineer")).role_category == "Frontend"
    assert classify_role(_job("Full-Stack Software Engineer")).role_category == "Full Stack"


def test_generic_software_engineer_falls_back_to_backend():
    assert classify_role(_job("Software Engineer")).role_category == "Backend"


def test_ml_wins_over_platform_when_title_says_ml_platform():
    # "Machine Learning" pattern is checked before "Platform / Infrastructure".
    assert classify_role(_job("Senior ML Platform Engineer")).role_category == "Machine Learning"


def test_ambiguous_title_with_no_signal_returns_none_not_jd_fallback():
    # Classification is title-only (see module docstring for why JD-body
    # fallback was removed) - an ambiguous title doesn't get a category
    # just because the JD happens to mention a relevant technology.
    job = classify_role(_job("Product Engineer", "You'll build our machine learning pipelines."))
    assert job.role_category is None


def test_non_software_role_returns_none():
    job = classify_role(_job("Marketing Manager", "Own our brand campaigns."))
    assert job.role_category is None


def test_recruiter_excluded_even_when_jd_mentions_software_engineers():
    # Real false positive caught in live testing: a recruiter's JD
    # naturally mentions "Software Engineers" (who they're hiring for),
    # which used to match the generic engineering fallback pattern.
    job = classify_role(
        _job(
            "Senior Technical Recruiter (Contract)",
            "You'll partner with hiring managers to recruit top Software "
            "Engineers and help us scale our engineering org.",
        )
    )
    assert job.role_category is None


def test_account_manager_excluded():
    job = classify_role(
        _job("Senior Account Manager", "You'll work closely with our engineering team on customer accounts.")
    )
    assert job.role_category is None


def test_sales_and_business_development_excluded():
    assert classify_role(_job("Sales Development Representative")).role_category is None
    assert classify_role(_job("Business Development Manager")).role_category is None


def test_product_manager_excluded_even_with_ai_in_jd():
    # Real false positive caught in live testing: several Product Manager
    # postings whose JD discussed the AI/ML product they manage were
    # getting classified as "AI / Generative AI" engineering roles.
    job = classify_role(
        _job(
            "Product Manager, Relevance and Personalization",
            "You'll drive our Generative AI and Machine Learning roadmap.",
        )
    )
    assert job.role_category is None


def test_hr_recruiting_and_localization_titles_excluded():
    assert classify_role(_job("People Partner")).role_category is None
    assert classify_role(_job("Talent Acquisition Partner")).role_category is None
    assert classify_role(_job("Localization Program Manager")).role_category is None
    assert classify_role(_job("Senior Compensation Partner, Technology")).role_category is None


def test_non_engineering_exclusion_checked_before_title_role_match():
    # A title that would otherwise match an engineering pattern should
    # still be excluded if it also names a non-engineering function.
    job = classify_role(_job("Recruiter - Software Engineering Roles"))
    assert job.role_category is None


def test_generic_company_boilerplate_in_jd_does_not_leak_into_role_category():
    # Real false positive caught in live testing: a company's "About us"
    # boilerplate ("Our expertise spans ... Machine Learning and Software
    # Engineering...") appeared at the top of every posting from that
    # company regardless of actual role, misclassifying a Power BI Data
    # Analyst posting as "Machine Learning" when JD-fallback still ran.
    job = classify_role(
        _job(
            "Mid Power BI Data Analyst",
            "At Acme, we're a tech-enabled professional services company. "
            "Our expertise spans Operations, Training, Engineering, "
            "Nanotechnology, Statistics, Machine Learning and Software "
            "Engineering.",
        )
    )
    assert job.role_category is None
