"""Runtime settings for the hosted API.

DATABASE_URL points at Postgres in Docker Compose. Tests override it with
SQLite so pytest does not need a running database.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://replay:replay@127.0.0.1:5432/replay"
    token_pepper: str = "dev-only-change-me"
    create_tables_on_startup: bool = True

    # Live LLM calls stay off unless both enabled and keyed.
    llm_enabled: bool = False
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
