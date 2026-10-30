from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables (and `.env`, `.env.local` in development).

    `neon env pull` writes `.env.local`, so a pulled Neon `DATABASE_URL` wins over `.env`.
    Real environment variables (Compose, Cloud Run) win over both files.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://bookrag:bookrag@localhost:5432/bookrag"
    # Direct (non-pooler) connection for migrations; falls back to `database_url`.
    database_url_unpooled: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
