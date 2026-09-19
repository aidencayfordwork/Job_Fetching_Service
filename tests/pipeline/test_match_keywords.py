from app.pipeline.match_keywords import match_keywords


def test_matches_languages_and_domains():
    title = "Senior Backend Engineer"
    jd = """
    We're looking for a Senior Backend Engineer to build our Python and Go
    services on AWS using Kubernetes and PostgreSQL. Experience with
    distributed systems and microservices required. Bonus: exposure to
    Generative AI / LLM work.
    """
    found = match_keywords(title, jd)

    assert "Python" in found
    assert "Go" in found
    assert "AWS" in found
    assert "Kubernetes" in found
    assert "PostgreSQL" in found
    assert "Distributed Systems" in found
    assert "Microservices" in found
    assert "Generative AI" in found
    assert "Large Language Models" in found
    assert "Backend" in found


def test_short_ambiguous_tokens_are_case_sensitive():
    # lowercase "go" as an ordinary English word should NOT match the Go language
    found = match_keywords("We go the extra mile for our customers.")
    assert "Go" not in found

    found_lang = match_keywords("Backend services written in Go and deployed via Docker.")
    assert "Go" in found_lang
    assert "Docker" in found_lang


def test_no_match_returns_empty_list():
    assert match_keywords(None, "") == []
    assert match_keywords("A generic sentence with no tech terms in it.") == []


def test_cpp_and_csharp_symbol_boundaries():
    found = match_keywords("Looking for C++ and C# developers, not JavaScript.")
    assert "C++" in found
    assert "C#" in found
    assert "JavaScript" in found


def test_aliases_of_case_sensitive_terms_match_in_any_casing():
    # "Go" itself is case-sensitive (English "go"), but "Golang" is not ambiguous.
    assert "Go" in match_keywords("We write Golang services")
    assert "Go" in match_keywords("we write golang services")
    assert "Go" not in match_keywords("we go above and beyond")
    assert "R" in match_keywords("Strong R Programming background")
