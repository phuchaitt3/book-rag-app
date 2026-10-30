# Build context: the repository root (the uv workspace lives there).
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so source edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/rag/pyproject.toml packages/rag/
RUN uv sync --frozen --no-dev --package book-rag-api --no-install-workspace

COPY apps/api/src apps/api/src
COPY apps/api/alembic.ini apps/api/
COPY apps/api/migrations apps/api/migrations
COPY packages/rag/src packages/rag/src
RUN uv sync --frozen --no-dev --package book-rag-api

FROM python:3.12-slim
RUN useradd --create-home app
WORKDIR /app
COPY --from=base --chown=app:app /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH" PORT=8080
EXPOSE 8080
# Cloud Run injects PORT; compose maps 8000 -> 8080.
CMD ["sh", "-c", "exec uvicorn book_rag_api.main:app --host 0.0.0.0 --port ${PORT}"]
