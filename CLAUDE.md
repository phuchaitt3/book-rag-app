# book-rag-app

Tier: **solo-fast** (confirmed by the user 2026-10-29; see the user-level working rules, "Project tiers").

Monorepo: `apps/api` (Python, FastAPI), `apps/web` (Next.js), `packages/rag`, `infra/`. Python tooling is uv (`uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`); web tooling is pnpm (`pnpm lint:web`, `pnpm typecheck:web`, `pnpm build:web`). CI (`.github/workflows/ci.yml`) runs exactly these.

This repository is **public**: everything committed or pushed is published.

## Hard limits (handoff files cannot relax these)

- Never read, copy or commit secrets: `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, `credentials*.json`.
- Never commit or push directly to `main`. All work goes through a short-lived branch and a pull request. `main` should be protected on GitHub (pull request required, required CI checks, no force-push).
- Agents may push their own feature branches (`feat/*`, `fix/*`, `chore/*`, `task/*`) without asking when lint, typecheck and tests pass locally and the diff contains no secret, local path, private identifier or data file. Never force-push.
- Ask the user before: changing repository settings or visibility, deleting a remote branch, deploying, or running anything that calls a paid API at scale.

## Pull requests: agent review, auto-merge (standing approval from the user, 2026-10-29)

- Agents open pull requests for their own branches without asking.
- The lead agent reviews every pull request it did not write (`/code-review`) and posts the result as a PR comment. A pull request written by the lead is reviewed by another chat.
- When every required check is green and the review found no blocking issue, the lead squash-merges (or enables auto-merge) and adds one line under "Done" in `.handoff/INBOX.md` with the PR number and the undo (`git revert <merge commit>` by pull request).
- The user must still merge any pull request that touches `CLAUDE.md`, `.github/`, `infra/`, deploy config, dependency lockfiles, or anything involving secrets or money.

## Working in several chats

Several Claude chats may work here at once. Use the `workflow:multi-chat` skill. The handoff folder is `.handoff/` in the main checkout (git-excluded). `RULES.md` holds the orchestration rules and `INBOX.md` is the task board and the user's status page.

Branching is trunk-based: `main` is the integration branch; each task is one short-lived branch in its own worktree, merged by pull request.
