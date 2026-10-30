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
- Reviews come from a pool, not a dedicated reviewer (like GitHub's team review auto-assignment): any chat other than the author claims the oldest open row in the "Review queue" of `.handoff/INBOX.md`, runs `/code-review`, and posts the result as a PR comment. An author never reviews its own pull request. Depth follows risk: user-merge items get `/security-review` or `/code-review high`, everything else `/code-review medium`. The lead takes a row no other chat picks up, except a pull request the lead wrote, which goes to the user.
- When the review found no blocking issue and the pull request is not a user-merge item, the reviewer enables auto-merge (`gh pr merge <n> --auto --squash`), so the required checks are the final gate, and adds one line to `.handoff/DONE.md` with the PR number and the undo (`git revert <merge commit>` by pull request). Run `gh pr` commands plain, not chained after `cd … &&`, or they miss the allow rules.
- The user must still merge any pull request that touches `CLAUDE.md`, `infra/`, deploy config, public positioning of the project (README claims, profile text), or anything involving secrets or money.
- Dependency lockfiles (`uv.lock`, `pnpm-lock.yaml`) are drawn by risk, like `.github/` (proposed 2026-10-30, needs the user's merge of this change; standard: supply-chain guidance says to review lockfile diffs as carefully as code, not that the owner must merge them; checked 2026-10-30). The reviewer reads the lockfile diff, lists every package it adds, removes or changes (name, old to new version) in the PR comment, and may merge when all of these hold: every changed package is named in the PR description; each is a new package or a patch or minor bump; all come from the default registry (PyPI, npm) with hashes kept; the PR touches no other user-merge path; and CI is green. The user merges a major bump, a package the PR does not name, a new registry or git source, or removed hashes.
- Under `.github/` the line is drawn by risk, not by path (user's decision, 2026-10-29; looser than GitHub's CODEOWNERS-on-all-workflows baseline because this repo is solo-fast, and a strict-tier project keeps the full gate). The user merges any change that touches secrets, `permissions:`, triggers (`on:`), `runs-on:`, deploy or release steps, adds or changes a third-party action, or puts a `${{ }}` expression from untrusted input (`github.event.*`, `github.head_ref`) into a `run:` step, and any `.github/` file that is not a workflow (CODEOWNERS, dependabot, templates). The reviewer may merge a workflow change limited to lint, test or build jobs after review and green CI, and states in the PR comment that none of the user-merge items is touched.
- A `PreToolUse` hook (`.claude/hooks/merge_gate.py`, enabled in `.claude/settings.json`) is a guardrail against mistakes, not a security boundary: it refuses `gh pr merge` (also inside `bash -c`, `$(...)` or `gh api`) on a pull request that touches these paths, and any `--admin` merge. GitHub's required checks and this rule are the hard gate. It refuses every `.github/` file (the risk exception above needs a judgment the hook cannot make), so the user merges those too.

## Working in several chats

Several Claude chats may work here at once. Use the `workflow:multi-chat` skill. The handoff folder is `.handoff/` in the main checkout (git-excluded). `RULES.md` holds the orchestration rules, `INBOX.md` is the user's one-screen status page, `tickets/` holds one file per task or decision, and `DONE.md` is the done log.

Branching is trunk-based: `main` is the integration branch; each task is one short-lived branch in its own worktree, merged by pull request.
