# Build context: the repository root (the uv workspace lives there).
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so source edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/rag/pyproject.toml packages/rag/
RUN uv sync --frozen --no-dev --package book-rag-worker --no-install-workspace

COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
COPY packages/rag/src packages/rag/src
RUN uv sync --frozen --no-dev --package book-rag-worker

FROM python:3.12-slim
RUN useradd --create-home app
WORKDIR /app
COPY --from=base --chown=app:app /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
# Create the queue tables if missing, then take jobs until stopped.
CMD ["sh", "-c", "python -m book_rag_worker init && exec python -m book_rag_worker run"]
