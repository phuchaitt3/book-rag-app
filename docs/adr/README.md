# Architecture decision records

Records of choices that are costly to reverse. Each states the context, the options, the decision, the reasoning and its consequences. *Accepted* means decided and in use; *Planned* means decided but not built yet.

Agents decide the architecture and record it here, following the `workflow:adr` skill; the owner may overrule. An ADR is short (about two pages), starts with the decision, and is `Accepted` in the PR that merges it ([process](../design/README.md)). Records written before 2026-11-27 link a study note and a review issue; those are history.

| # | Decision | Status | Decided by |
|---|---|---|---|
| [0001](0001-monorepo-uv-pnpm.md) | Monorepo with a uv workspace and a pnpm workspace | Accepted | owner |
| [0002](0002-postgres-pgvector-hybrid-search.md) | PostgreSQL with pgvector and full-text search, no separate vector database | Accepted | agents |
| [0003](0003-model-provider-interfaces.md) | Every model sits behind a provider interface | Accepted | agents |
| [0004](0004-ingestion-queue-in-postgres.md) | Ingestion queue in Postgres (Procrastinate), no Redis | Accepted | agents |
| [0005](0005-application-first-then-evals.md) | Build the application first, then improve the RAG logic against an eval set | Accepted | agents |
| [0006](0006-better-auth.md) | Better Auth, with users in our own Postgres | Planned | agents |
| [0007](0007-api-web-contract.md) | The web app learns the API's shape from a generated OpenAPI file | Accepted | agents |
| [0008](0008-qdrant-vector-search-experiment.md) | Qdrant vector-search experiment, exit criteria fixed before any run | Rejected | agents |
| [0009](0009-reranker-local-tei-service.md) | The reranker runs locally as a TEI service; production hosting is decided at deployment | Accepted | owner (local only), agents (details) |
| [0010](0010-metrics-endpoint-prometheus.md) | The API serves Prometheus metrics at /metrics; retrieval reports through an observer | Accepted | agents |
| [0011](0011-bm25-in-postgres-stored-statistics.md) | The full-text leg ranks with BM25 computed in Postgres from stored per-book statistics | Accepted | agents |

## Template for new records

About two pages, change log excluded. A small decision (a lint tool, a naming rule) needs only Context, Decision, Why and the change log. One decision per record. Once a record is accepted it is frozen: a changed decision is a new ADR that supersedes it, and the old record is not edited to follow the code or a later ADR. The only edits are a typo or broken link, the `Superseded by NNNN` status line, and a dated clarification of wording that was unclear when written, each with a change-log line ([docs/design/README.md](../design/README.md), "Accepted ADRs are frozen").

```markdown
# NNNN: <the decision, in a few words>

**Status:** Proposed | Accepted | Planned | Superseded by NNNN | Rejected   **Date:** YYYY-MM-DD
**Decided by:** agents | owner   **Confidence:** high | medium | low
**Study note** (optional): [docs/design/NNNN-<slug>.md](../design/NNNN-<slug>.md)

## Context
The forces, stated neutrally: the problem, requirements with numbers (marked measured or estimated, with the date), constraints.

## Options considered
Each real option in two to four lines: what it is, its main pro and con.

## Decision
One to three sentences.

## Why
Why this option beat the others, and the assumptions that would change the answer.

## Consequences
Good, bad and neutral; follow-up decisions; known gaps as one line with an issue link; the next step as load grows (one line each).

## Change log
Dated one-line entries, newest last, each with the issue or PR that caused it.
```
