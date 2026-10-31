import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import procrastinate
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from book_rag.providers import LLM, Embedder, FakeEmbedder, FakeLLM, OllamaEmbedder, OllamaLLM
from book_rag.retrieval import HybridRetriever
from book_rag_api.books import router as books_router
from book_rag_api.config import Settings, get_settings
from book_rag_api.db import create_engine, ping
from book_rag_api.jobs import create_queue
from book_rag_api.jobs import router as jobs_router
from book_rag_api.models import EMBEDDING_DIM
from book_rag_api.retrieval import SqlChunkSearcher
from book_rag_api.routers.chat import router as chat_router
from book_rag_api.storage import ObjectStorage, S3Storage


def create_app(
    settings: Settings | None = None,
    *,
    storage: ObjectStorage | None = None,
    queue: procrastinate.App | None = None,
    llm: LLM | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """Tests pass a fake `storage`, an in-memory `queue`, and fake `llm` and `embedder`."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = create_engine(settings.database_url)
        app.state.storage = storage or _s3_storage(settings)
        app.state.queue = queue or create_queue(settings.database_url)
        app.state.llm = llm or _llm(settings)
        app.state.retriever = HybridRetriever(
            SqlChunkSearcher(async_sessionmaker(app.state.engine)),
            embedder or _embedder(settings),
        )
        try:
            async with app.state.queue.open_async():
                yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="book-rag-app API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(jobs_router)
    app.include_router(books_router)
    app.include_router(chat_router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up. Never touches the database."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz(engine: Annotated[AsyncEngine, Depends(get_engine)]) -> JSONResponse:
        """Readiness: the database answers."""
        try:
            await ping(engine)
        except (OSError, TimeoutError, SQLAlchemyError):
            return JSONResponse(
                {"status": "unavailable", "database": "down"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JSONResponse({"status": "ok", "database": "up"})

    return app


def _llm(settings: Settings) -> LLM:
    if settings.llm_provider == "fake":
        return FakeLLM()
    if settings.llm_provider == "ollama":
        return OllamaLLM(settings.llm_model, settings.ollama_url)
    raise ValueError(f"unknown llm provider {settings.llm_provider!r}")


def _embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder(EMBEDDING_DIM)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.embedding_model, EMBEDDING_DIM, settings.ollama_url)
    raise ValueError(f"unknown embedding provider {settings.embedding_provider!r}")


def _s3_storage(settings: Settings) -> S3Storage:
    s3 = S3Storage(
        endpoint_url=settings.s3_endpoint_url,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
    )
    try:
        s3.ensure_bucket()
    except Exception:  # storage may come up later; uploads fail until it does
        logging.getLogger(__name__).warning("object storage is not reachable at startup")
    return s3


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


app = create_app()
