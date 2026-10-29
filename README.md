# Book RAG

Ask questions about Vietnamese books and get answers with citations to the section and page.

> Work in progress. This is the rebuild of a [university project](https://github.com/phuchaitt3/book-rag) (v1).

## Stack

| Layer | Tech |
|---|---|
| Web | Next.js 16 (App Router), TypeScript, Tailwind CSS |
| API | FastAPI, Pydantic settings, SQLAlchemy 2 (async) |
| Data | PostgreSQL + pgvector |
| Tooling | uv workspace, pnpm workspace, ruff, mypy (strict), pytest, GitHub Actions |

## Layout

```
apps/web        Next.js frontend
apps/api        FastAPI backend
packages/rag    RAG core (pure Python, unit-tested)
infra/          database init and deploy configs
```

## Run locally

Requires Docker and pnpm. [uv](https://docs.astral.sh/uv/) is needed only for the checks below.

```sh
pnpm stack:up      # Postgres + pgvector, API on :8000, web on :3000 (all in Docker)
pnpm stack:down    # stop and remove everything (data is kept in the db-data volume)
pnpm stack:dev     # same as up, in the foreground with hot reload (docker compose watch)
```

The home page shows whether the API is reachable. `GET /healthz` is liveness; `GET /readyz` also checks the database.

## Checks

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
pnpm lint:web && pnpm typecheck:web && pnpm build:web
```
