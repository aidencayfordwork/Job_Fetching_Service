from app.config import Settings


def test_plain_postgres_urls_get_the_asyncpg_driver():
    s = Settings(
        database_url="postgresql://u:p@postgres.railway.internal:5432/railway",
        bidflow_database_url="postgres://w:p@postgres.railway.internal:5432/railway",
    )
    assert s.database_url == "postgresql+asyncpg://u:p@postgres.railway.internal:5432/railway"
    assert s.bidflow_database_url == "postgresql+asyncpg://w:p@postgres.railway.internal:5432/railway"
    assert Settings(bidflow_database_url="").bidflow_database_url == ""
    assert Settings(database_url="postgresql+asyncpg://x/y").database_url == "postgresql+asyncpg://x/y"
