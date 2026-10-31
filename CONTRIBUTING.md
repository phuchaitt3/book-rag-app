# Contributing

This is a portfolio project, but the workflow is the one a team would use.

## Workflow

- `main` is protected: every change is a pull request from a short-lived branch, with the required CI checks green. No direct pushes, no force-pushes.
- Branch names: `feat/<id>-<slug>`, `fix/...`, `chore/...`, `docs/...`, `task/...`.
- One pull request is one coherent change, with its tests and docs. Commit messages: a short imperative subject, then a body that explains why.
- Link the issue in the PR description with `Closes #n`.
- Pull requests that touch the paths in [CODEOWNERS](.github/CODEOWNERS) need the owner's review.

## Setup and checks

See the README for running the stack. Before pushing:

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
pnpm lint:web && pnpm typecheck:web && pnpm build:web
```

After you change an API route or a response model, run `pnpm gen:api` and commit `apps/web/src/api/openapi.json` and `schema.d.ts` (ADR 0007). Run it, not `pnpm --filter web gen:types` alone, which would only regenerate the types from an out-of-date `openapi.json`.

`pre-commit install` runs the same lint and type checks on every commit (see the README).

## Design decisions

Significant choices are recorded as decision records in [docs/adr/](docs/adr/). Add one when a pull request changes a recorded choice or makes a new one that is costly to reverse.

## Secrets

Never commit `.env` files, keys or tokens (`.env.example` holds placeholders only). Secret scanning with push protection is on for this repository.
