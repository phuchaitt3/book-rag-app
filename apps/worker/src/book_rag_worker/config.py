from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Worker settings, from environment variables (and `.env`, `.env.local` in development)."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://bookrag:bookrag@localhost:5432/bookrag"
    # Where uploaded PDFs live (Book.storage_key is a path below it).
    storage_dir: Path = Path("storage")
    # When set, uploads are read from this S3-compatible store instead of `storage_dir`.
    s3_endpoint_url: str | None = None
    s3_bucket: str = "books"
    s3_access_key: str = "local"
    s3_secret_key: str = "local"
    s3_region: str = "auto"
    embedding_provider: str = "ollama"  # "ollama", or "fake" (no model, for tests)
    embedding_model: str = "bge-m3"
    ollama_url: str = "http://localhost:11434"
    embed_batch_size: int = 32
    # A job queued or running longer than this is failed by the periodic sweep.
    stuck_job_minutes: int = 60


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
