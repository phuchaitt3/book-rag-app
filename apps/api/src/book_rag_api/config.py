from functools import lru_cache
from typing import Literal

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
    # S3-compatible object storage: SeaweedFS locally, Cloudflare R2 in production.
    s3_endpoint_url: str = "http://localhost:8333"
    s3_bucket: str = "books"
    s3_access_key: str = "local"
    s3_secret_key: str = "local"
    s3_region: str = "auto"
    max_upload_bytes: int = 50 * 1024 * 1024
    max_upload_pages: int = 1000
    # Chat: "ollama" or "fake" (no model, for tests and load tests). The embedding model must
    # match the one the worker used to embed the chunks.
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:7b-instruct"
    embedding_provider: str = "ollama"
    embedding_model: str = "bge-m3"
    ollama_url: str = "http://localhost:11434"
    # Experiment (ADR 0008): "pgvector" (default), "qdrant", or "shadow" (pgvector answers and
    # Qdrant is compared in the log). EXPIRES 2026-12-15, see #120.
    vector_store: Literal["pgvector", "qdrant", "shadow"] = "pgvector"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
