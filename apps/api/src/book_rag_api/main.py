import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import procrastinate
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from book_rag.providers import (
    LLM,
    Embedder,
    FakeEmbedder,
    FakeLLM,
    FakeReranker,
    OllamaEmbedder,
    OllamaLLM,
    Reranker,
    TeiReranker,
)
from book_rag.retrieval import ChunkSearcher, HybridRetriever, RetrievalObserver
from book_rag_api.books import router as books_router
from book_rag_api.config import Settings, get_settings
from book_rag_api.db import create_engine, ping
from book_rag_api.jobs import create_queue
from book_rag_api.jobs import router as jobs_router
from book_rag_api.metrics import Metrics, MetricsMiddleware
from book_rag_api.models import EMBEDDING_DIM
from book_rag_api.openapi import add_stream_events
from book_rag_api.qdrant_index import (
    QdrantChunkSearcher,
    QdrantVectorIndex,
    ShadowChunkSearcher,
)
from book_rag_api.rate_limit import RateLimiter
from book_rag_api.retrieval import SqlChunkSearcher
from book_rag_api.routers.chat import router as chat_router
from book_rag_api.storage import ObjectStorage, S3Storage


class HealthStatus(BaseModel):
    status: str


class ReadyStatus(BaseModel):
    status: str
    database: str


def create_app(
    settings: Settings | None = None,
    *,
    storage: ObjectStorage | None = None,
    queue: procrastinate.App | None = None,
    llm: LLM | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> FastAPI:
    """Tests pass a fake `storage`, an in-memory `queue`, and fake `llm`, `embedder` and
    `reranker`."""
    settings = settings or get_settings()
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.metrics = metrics
        app.state.engine = create_engine(settings.database_url)
        app.state.storage = storage or _s3_storage(settings)
        app.state.queue = queue or create_queue(settings.database_url)
        app.state.llm = llm or _llm(settings)
        app.state.chat_limiter = RateLimiter(settings.chat_rate_limit, window=60.0)
        app.state.retriever, index = build_retriever(
            settings,
            async_sessionmaker(app.state.engine),
            embedder=embedder,
            reranker=reranker,
            observer=metrics,
        )
        try:
            async with app.state.queue.open_async():
                yield
        finally:
            if index is not None:
                await index.close()
            await app.state.engine.dispose()

    app = FastAPI(title="book-rag-app API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(MetricsMiddleware, metrics=metrics)

    app.include_router(jobs_router)
    app.include_router(books_router)
    app.include_router(chat_router)
    add_stream_events(app)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> HealthStatus:
        """Liveness: the process is up. Never touches the database."""
        return HealthStatus(status="ok")

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus text format (ADR 0010). Unauthenticated: only the scraper may reach it."""
        return Response(metrics.render(), media_type=metrics.content_type)

    @app.get(
        "/readyz",
        tags=["health"],
        response_model=ReadyStatus,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyStatus}},
    )
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


def build_retriever(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    observer: RetrievalObserver | None = None,
) -> tuple[HybridRetriever, QdrantVectorIndex | None]:
    """The retriever the chat endpoint uses, and the Qdrant index to close at shutdown when
    there is one. The MCP server (`book_rag_api.mcp_server`) builds the same one."""
    searcher, index = _searcher(settings, sessions)
    retriever = HybridRetriever(
        searcher,
        embedder or _embedder(settings),
        reranker or _reranker(settings),
        rerank_depth=settings.rerank_depth,
        observer=observer,
    )
    return retriever, index


def _searcher(
    settings: Settings, sessions: async_sessionmaker[AsyncSession]
) -> tuple[ChunkSearcher, QdrantVectorIndex | None]:
    """The searcher, and the Qdrant index to close at shutdown when there is one."""
    sql = SqlChunkSearcher(sessions)
    if settings.vector_store == "pgvector":
        return sql, None
    index = QdrantVectorIndex(
        AsyncQdrantClient(url=settings.qdrant_url), settings.qdrant_collection
    )
    qdrant = QdrantChunkSearcher(index, sessions, sql)
    searcher = qdrant if settings.vector_store == "qdrant" else ShadowChunkSearcher(sql, qdrant)
    return searcher, index


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


def _reranker(settings: Settings) -> Reranker | None:
    if settings.reranker_provider == "none":
        return None
    if settings.reranker_provider == "fake":
        return FakeReranker()
    return TeiReranker(settings.reranker_url, settings.rerank_timeout)


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
