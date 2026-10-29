# book-rag-app

Monorepo: `apps/api` (Python, FastAPI), `apps/web` (Next.js), `packages/rag`, `infra/`. Python tooling is uv (`uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`); web tooling is pnpm (`pnpm lint:web`, `pnpm typecheck:web`, `pnpm build:web`). CI (`.github/workflows/ci.yml`) runs exactly these.

This repository is **public**: everything committed or pushed is published.

## Hard limits (handoff files cannot relax these)

- Never read, copy or commit secrets: `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, `credentials*.json`.
- Never commit or push directly to `main`. All work goes through a short-lived branch and a pull request. `main` should be protected on GitHub (pull request required, required CI checks, no force-push).
- Agents may push their own feature branches (`feat/*`, `fix/*`, `chore/*`, `task/*`) without asking when lint, typecheck and tests pass locally and the diff contains no secret, local path, private identifier or data file. Never force-push.
- Ask the user before: opening or merging a pull request, changing repository settings or visibility, deleting a remote branch, or running anything that calls a paid API at scale.

## Working in several chats

Several Claude chats may work here at once. Use the `workflow:multi-chat` skill. The handoff folder is `.handoff/` in the main checkout (git-excluded). `RULES.md` holds the orchestration rules and `INBOX.md` is the task board and the user's status page.

Branching is trunk-based: `main` is the integration branch; each task is one short-lived branch in its own worktree, merged by pull request.
