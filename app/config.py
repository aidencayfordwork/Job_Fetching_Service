import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://jobfetch:jobfetch@localhost:5432/jobfetch"
    # Postgres schema for the platform's own tables. "platform" when sharing
    # BidFlow's database (docs/bidflow/COLLABORATION.md §15a).
    database_schema: str = Field(default="public", pattern=r"^[a-z_][a-z0-9_]*$")
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

    # BidFlow job feed (docs/bidflow/JOB_FEED_CONTRACT.md). Publishing is
    # off while the URL is empty. Use the asyncpg form:
    # postgresql+asyncpg://jobfeed_writer:<password>@<host>:<port>/<db>
    bidflow_database_url: str = ""
    # "require" in production (the contract mandates TLS); "disable" only for
    # the local replica.
    bidflow_ssl: str = "require"
    publish_interval_seconds: int = 10 * 60

    @field_validator("database_url", "bidflow_database_url")
    @classmethod
    def _use_asyncpg_driver(cls, url: str) -> str:
        # Accept plain Postgres URLs as Railway and most hosts print them.
        return re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
