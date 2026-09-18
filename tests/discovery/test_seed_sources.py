from app.discovery.seed_sources import load_static_seed_companies


def test_load_static_seed_companies_returns_nonempty_list():
    companies = load_static_seed_companies()
    assert isinstance(companies, list)
    assert len(companies) > 10
    assert "Airbnb" in companies
    assert all(isinstance(c, str) and c.strip() for c in companies)
