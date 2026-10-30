# 0001: Monorepo with a uv workspace and a pnpm workspace

**Status:** Accepted

**Decided by:** agents, before study-design mode; not yet reviewed by the owner

## Context
The project has a Next.js frontend, a FastAPI backend and a pure-Python RAG core that should be testable on its own.

## Decision
One repository: `apps/web` (pnpm), `apps/api` and `packages/rag` (uv workspace), `infra/`. CI and pre-commit run the same checks on all of it.

## Consequences
- One pull request can change the API and the web app together, and one clone runs everything.
- Two lockfiles (`uv.lock`, `pnpm-lock.yaml`). Dependency changes are their own small pull requests so the lockfiles do not conflict.
