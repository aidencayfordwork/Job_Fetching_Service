from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://jobfetch:jobfetch@localhost:5432/jobfetch"
    api_key: str = "dev-local-key"
    log_level: str = "INFO"

    default_fetch_interval_seconds: int = 3 * 60 * 60
    discovery_interval_seconds: int = 7 * 24 * 60 * 60
    scheduler_enabled: bool = True

    # Jobs posted before this many days ago are excluded by the filter
    # stage, regardless of source - keeps the dataset to recent postings
    # instead of accumulating months-old listings from a source's full
    # catalog.
    max_job_age_days: int = 7

    # Adzuna/Jooble connectors are implemented but stay disabled (see
    # sources table) until these are set - free signup at
    # https://developer.adzuna.com/signup (Adzuna) and a requested key at
    # https://jooble.org/api/about (Jooble).
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jooble_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
