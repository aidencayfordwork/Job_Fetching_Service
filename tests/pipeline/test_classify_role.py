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


def test_falls_back_to_jd_when_title_has_no_signal():
    job = classify_role(_job("Product Engineer", "You'll build our machine learning pipelines."))
    assert job.role_category == "Machine Learning"


def test_non_software_role_returns_none():
    job = classify_role(_job("Marketing Manager", "Own our brand campaigns."))
    assert job.role_category is None
