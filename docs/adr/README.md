# Architecture decision records

Short records of choices that are costly to reverse. Each states the context, the decision and its consequences. *Accepted* means decided and in use; *Planned* means decided but not built yet.

This project is also a system design study (see [docs/design](../design/README.md)). The owner decides architecture and writes the reasoning in each new ADR. The records below were written by agents before that started; the owner reviews each one and either confirms it in their own words or replaces it with a new ADR.

| # | Decision | Status | Decided by |
|---|---|---|---|
| [0001](0001-monorepo-uv-pnpm.md) | Monorepo with a uv workspace and a pnpm workspace | Accepted | owner (draft, edit pending) |
| [0002](0002-postgres-pgvector-hybrid-search.md) | PostgreSQL with pgvector and full-text search, no separate vector database | Accepted | agents, owner review pending |
| [0003](0003-model-provider-interfaces.md) | Every model sits behind a provider interface | Accepted | agents, owner review pending |
| [0004](0004-ingestion-queue-in-postgres.md) | Ingestion queue in Postgres (Procrastinate), no Redis | Accepted | agents, owner review pending |
| [0005](0005-application-first-then-evals.md) | Build the application first, then improve the RAG logic against an eval set | Accepted | agents, owner review pending |
| [0006](0006-better-auth.md) | Better Auth, with users in our own Postgres | Planned | agents, owner review pending |

## Template for new records

```markdown
# NNNN: <decision in a few words>

**Status:** Proposed | Accepted | Planned | Superseded by NNNN

**Decided by:** owner (brief: docs/design/<brief>.md)

## Context
The problem and the requirements that matter, with numbers.

## Options considered
Each option with its main trade-off.

## Decision
What was chosen, in the owner's words.

## Why
The reasoning that ruled the other options out.

## Consequences
What gets easier, what gets harder, what this commits us to.

## At 1000x the load
What breaks first, and what the next step would be.
```
