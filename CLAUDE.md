# book-rag-app

Tier: **solo-fast** (confirmed by the user 2026-10-29; see the `workflow:new-project` skill).

Mode: **study-design** (chosen by the user 2026-10-30; see the `workflow:new-project` skill). Design briefs go in `docs/design/`, decisions in `docs/adr/`; [docs/design/README.md](docs/design/README.md) describes the process.

Goals: this is a portfolio project, and **scalability and operability come before features** (the user's statement, 2026-10-31; full list in [README.md](README.md), "Goals and priorities"). Read that section before any design, ADR or dependency choice, and judge options by the design that scales and by measurement, not by today's load alone.

Monorepo: `apps/api` (Python, FastAPI), `apps/web` (Next.js), `packages/rag`, `infra/`. Python tooling is uv (`uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`); web tooling is pnpm (`pnpm lint:web`, `pnpm typecheck:web`, `pnpm build:web`). CI (`.github/workflows/ci.yml`) runs exactly these.

This repository is **public**: everything committed or pushed is published.

## Hard limits (handoff files cannot relax these)

- Never read, copy or commit secrets: `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, `credentials*.json`.
- Never commit or push directly to `main`. All work goes through a short-lived branch and a pull request. `main` should be protected on GitHub (pull request required, required CI checks, no force-push).
- Agents may push their own feature branches (`feat/*`, `fix/*`, `chore/*`, `task/*`) without asking when lint, typecheck and tests pass locally and the diff contains no secret, local path, private identifier or data file. Never force-push.
- Ask the user before: changing repository settings or visibility, deleting a remote branch, deploying, or running anything that calls a paid API at scale.

## Pull requests: agent review, auto-merge (standing approval from the user, 2026-10-29)

Agents open pull requests for their own branches without asking, and review and merge them as the `workflow:pr-review` skill says (review from a pool, depth by risk, auto-merge when the review finds no blocking issue and the pull request is not a user-merge item). This project adds:

- When the reviewer enables auto-merge, it also adds one line to `.handoff/DONE.md` with the PR number and the undo (`git revert <merge commit>` by pull request).
- The user must still merge any pull request that touches `.claude/` (agent settings and hooks), `infra/`, deploy config, or anything involving secrets or money. `README.md` and other docs are ordinary files: the reviewer checks that a change describing what the project does matches the code, and may merge it (user's decision, 2026-11-01; departs from the usual public-facing-content review because solo-fast trades gates for speed and a README change is undone by a revert). `CLAUDE.md` and `.github/` are ordinary files too: the reviewer checks them and may merge them, because the agent already asks the user through `AskUserQuestion` before any rule change, so a merge step added nothing (user's decision, 2026-11-01; follows workflow 0.16.0). The `.github/` bullet below still applies. `LICENSE` and `SECURITY.md` stay user-merge items. [.github/CODEOWNERS](.github/CODEOWNERS) holds the path list; GitHub would enforce it once the ruleset option in #135 is on, and until then the hook below and this rule do, refusing the same paths, and a test fails when the two differ (user's decision, 2026-11-01; standard: GitHub code owners with required code-owner review, and agent config files gated like CI config (vendor guidance, no formal standard), checked 2026-11-01; departs from standard: "Require review from Code Owners" stays off in solo-fast to keep merges fast, until #135). Deploy config means files that build or run the production or CI system (Dockerfiles, `neon.ts`, `vercel.json`, deploy steps in workflows). The local-only `compose.yaml` is not deploy config: the reviewer may merge a change to it when the change adds no secret value and publishes no new port for a service without authentication, and says so in the review comment (user's decision, 2026-11-01).
- Dependency lockfiles (`uv.lock`, `pnpm-lock.yaml`) are drawn by risk, like `.github/` (proposed 2026-10-30, needs the user's merge of this change; standard: supply-chain guidance says to review lockfile diffs as carefully as code, not that the owner must merge them; checked 2026-10-30). The reviewer reads the lockfile diff, lists every package it adds, removes or changes (name, old to new version) in the PR comment, and may merge when all of these hold: every changed package is named in the PR description; each is a new package or a patch or minor bump; all come from the default registry (PyPI, npm) with hashes kept; the PR touches no other user-merge path; and CI is green. The user merges a major bump, a package the PR does not name, a new registry or git source, or removed hashes.
- Under `.github/` the line is drawn by risk, not by path (user's decision, 2026-10-29; relaxed 2026-11-01; looser than GitHub's CODEOWNERS-on-all-workflows baseline because this repo is solo-fast, and a strict-tier project keeps the full gate). The user merges a `.github/` change only when it touches secrets or deploy or release steps. For a change to `permissions:`, triggers (`on:`), `runs-on:`, a third-party action, or a `${{ }}` expression from untrusted input (`github.event.*`, `github.head_ref`) in a `run:` step, the reviewer reads the diff with extra care and says in the PR comment what it checked. Any other `.github/` file (CODEOWNERS, dependabot, templates) is an ordinary file.
- A `PreToolUse` hook (`.claude/hooks/merge_gate.py`, enabled in `.claude/settings.json`) is a guardrail against mistakes, not a security boundary: it refuses `gh pr merge` (also inside `bash -c`, `$(...)` or `gh api`) on a pull request that touches these paths, and any `--admin` merge. GitHub's required checks and this rule are the hard gate. It does not refuse `.github/` files (the risk line above needs a judgment the hook cannot make), so the reviewer carries that check.

## Working in several chats

Several Claude chats may work here at once. Use the `workflow:multi-chat` skill. The handoff folder is `.handoff/` in the main checkout (git-excluded). Rules about what a chat may do live in this file, so a change to them is a pull request the user merges. `RULES.md` holds facts and claims only (paths, reserved slots, machine state, procedures); `INBOX.md` is the user's one-screen status page, `tickets/` holds one file per task or decision, and `DONE.md` is the done log.

Branching is trunk-based: `main` is the integration branch; each task is one short-lived branch in its own worktree, merged by pull request.

- Only one open pull request may change `CLAUDE.md` at a time. A second change waits for the first to merge, or joins the open PR with its author's agreement (user's decision, 2026-10-30, after #9 and #10 conflicted).
- Dependency changes (`pnpm-lock.yaml`, `uv.lock`) are their own task, one in progress at a time.
- `.handoff/` is its own private git repo, nested here and git-excluded. Never copy its contents into this repository, never put `.env*` or other secrets in it, and never push it anywhere else.
- The limits on items waiting for the user (3 items, 2 days, the daily digest) are the `workflow:multi-chat` skill's defaults; changing them needs the user's yes.
