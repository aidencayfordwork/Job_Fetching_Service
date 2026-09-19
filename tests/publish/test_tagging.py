from app.publish.tagging import choose_tags, requirements_text


def test_bidflow_worked_example(catalog):
    # JOB_PLATFORM_DB_PROMPT §9, verbatim.
    jd = (
        "Senior Backend Engineer — build our payments APIs in Python/FastAPI on PostgreSQL, "
        "deployed on AWS with Kubernetes. Kafka experience is a plus."
    )
    choice = choose_tags("Senior Backend Engineer", "Backend", jd, catalog)
    assert choice.tags[0] == "backend"
    assert set(choice.tags) == {"backend", "python", "fastapi", "postgresql", "aws", "kubernetes", "api design"}


def test_company_working_in_ai_does_not_make_the_job_an_ai_job(catalog):
    jd = (
        "About Acme\nWe are an AI company building generative AI and machine learning products.\n\n"
        "Requirements\n- 5+ years building services in Go and PostgreSQL\n- Kubernetes in production"
    )
    choice = choose_tags("Senior Backend Engineer", "Backend", jd, catalog)
    assert not {"ai", "genai", "ml"} & set(choice.tags)
    assert {"backend", "go", "postgresql", "kubernetes"} <= set(choice.tags)


def test_role_tags_come_from_the_title(catalog):
    assert choose_tags("Staff Machine Learning Engineer", "Machine Learning", "Python and PyTorch.", catalog).tags[0] == "ml"
    assert choose_tags("Senior MLOps Engineer", "MLOps", "Kubernetes.", catalog).tags[0] == "mlops"
    assert choose_tags("Senior GenAI Engineer", "AI / Generative AI", "Python.", catalog).tags[0] == "genai"
    assert choose_tags("Senior Data Engineer", "Data Engineering", "Spark and Airflow.", catalog).tags[0] == "data engineering"
    assert choose_tags("Senior Android Engineer", "Mobile / Android / iOS", "Kotlin.", catalog).tags[0] == "android"


def test_nice_to_have_sections_and_sentences_are_ignored(catalog):
    jd = (
        "Requirements\n- Python and PostgreSQL. Terraform is a plus.\n\n"
        "Nice to have\n- Kafka\n- Spark\n\n"
        "Benefits\n- AWS credits for side projects"
    )
    tags = set(choose_tags("Senior Backend Engineer", "Backend", jd, catalog).tags)
    assert {"python", "postgresql"} <= tags
    assert not {"terraform", "kafka", "spark", "aws"} & tags


def test_generic_software_engineer_title_decided_from_requirements(catalog):
    backend_jd = "Requirements\n- Go, PostgreSQL and Kafka microservices"
    assert choose_tags("Senior Software Engineer", "Backend", backend_jd, catalog).tags[0] == "backend"
    full_jd = "Requirements\n- Python and PostgreSQL APIs\n- React and TypeScript front ends"
    tags = choose_tags("Senior Software Engineer", "Backend", full_jd, catalog).tags
    assert "fullstack" in tags and "backend" not in tags
    assert not {"backend", "fullstack"} & set(choose_tags("Senior Software Engineer", "Backend", "Requirements\n- SQL", catalog).tags)


def test_ambiguous_words_are_not_tags(catalog):
    jd = "Requirements\n- Go above and beyond; a swift learner; cloud-first mindset; mobile stipend"
    tags = set(choose_tags("Senior Backend Engineer", "Backend", jd, catalog).tags)
    assert not {"go", "swift", "cloud", "mobile"} & tags


def test_skills_missing_from_the_catalog_are_sent_as_unknown(catalog):
    choice = choose_tags("Senior Backend Engineer", "Backend", "Requirements\n- Rust and GraphQL\n- C++ services", catalog)
    assert {"rust", "graphql", "c++"} <= set(choice.unknown)
    assert "c" not in choice.unknown
    assert not set(choice.unknown) & set(choice.tags)


def test_tags_are_stable_and_capped(catalog):
    jd = "Requirements\n- " + ", ".join(
        ["Python", "Go", "Java", "Kotlin", "SQL", "PostgreSQL", "Kafka", "Spark", "Airflow", "dbt",
         "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform", "React", "TypeScript"]
    )
    first = choose_tags("Senior Backend Engineer", "Backend", jd, catalog)
    assert first == choose_tags("Senior Backend Engineer", "Backend", jd, catalog)
    assert len(first.tags) <= 15


def test_requirements_text_drops_company_and_benefit_sections():
    jd = "About Acme\nWe love Kafka.\n\nAbout the role\nYou write Go.\n\nWhat we offer\nSpark days off."
    assert requirements_text(jd) == "About the role\nYou write Go."
