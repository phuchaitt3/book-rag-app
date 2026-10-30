## What and why

<!-- One or two sentences: what changes, and why. -->

Closes #

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
- [ ] `pnpm lint:web && pnpm typecheck:web && pnpm build:web` (if `apps/web` changed)
- [ ] No secret, local path, private identifier or data file in the diff
