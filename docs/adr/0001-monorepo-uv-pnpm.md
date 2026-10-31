# 0001: Monorepo with a uv workspace and a pnpm workspace

**Status:** Accepted

**Decided by:** owner, from the owner's own review answers (2026-10-30). Lines tagged *[agent-added]* were added by an agent from the review discussion. The owner kept them on purpose as a record of what the original answer covered.

## Context
The project has a Next.js frontend, a FastAPI backend, a background worker and a pure-Python RAG core that should be testable on its own.

*[agent-added]* Today: one developer plus several agent chats working in parallel, four deployable or reusable parts that ship together, and no separate teams or release schedules.

## Options considered
*[agent-added]*
- **Separate repositories** (polyrepo): independent releases, permissions and CI per part. Cost: a change that spans parts becomes several PRs merged in order, and the shared RAG code has to be published as a package.
- **One repository with a change-detection tool** (Nx, Turborepo): CI runs only what changed. Not needed at this size.
- **One repository, a single Python package:** no workspace. Gives up testing the RAG core alone and keeps the API and worker dependencies mixed.

## Decision
One repository: `apps/web` (pnpm), `apps/api`, `apps/worker` and `packages/rag` (uv workspace), `infra/`. CI and pre-commit run the same checks on all of it.

## Why
- Easier PR management: a change that touches several parts is one PR, not PRs across repos.
- One developer and one bot (several chats, in fact), so there is no multi-team orchestration and no individual schedules to coordinate.
- `packages/rag` is a central place for shared Python code: the Python packages share it easily, there is no duplicated package, and it is tracked in one place only.
- *[agent-added]* `packages/rag` declares only one outside dependency (`pypdfium2`, for reading PDFs) and imports no web framework, database or queue code, so its tests run without a database or web server. A separate package keeps that boundary visible: adding such an import would also mean adding the library to its `pyproject.toml`.

## Consequences
- One pull request can change the API and the web app together, and one clone runs everything.
- Two lockfiles (`uv.lock`, `pnpm-lock.yaml`). Dependency changes are their own small pull requests so the lockfiles do not conflict.
- *[agent-added]* The uv lockfile is shared: a dependency added to the worker changes `uv.lock`, so the API's Docker dependency layer is rebuilt although the API did not change. Standard mitigations (BuildKit cache mounts, CI layer caching) exist; measure before acting.
- *[agent-added]* The web app hardcodes the API's address and paths and nothing checks the contract between them. Tracked in #46.

## At 1000x the load
Repository size does not grow with traffic, so this reads as "if the team grew to 30 people".

- A monorepo needs strict orchestration, because several people work on the same shared files in one repository, and people can end up on the same issue without it.
- *[agent-added]* Conflicts concentrate in shared files (the lockfile, CI and root configuration), and CI time grows because every PR runs checks for the whole repository. Both have standard answers: folder ownership (CODEOWNERS, already in use here) and CI that runs only the affected parts. If those stop being enough, the next step is extracting a folder into its own repository, which keeps its history.
