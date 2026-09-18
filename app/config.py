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


@lru_cache
def get_settings() -> Settings:
    return Settings()
