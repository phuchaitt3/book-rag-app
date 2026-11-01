# Architecture decision records

Records of choices that are costly to reverse. Each states the context, the options, the decision, the reasoning and its consequences. *Accepted* means decided and in use; *Planned* means decided but not built yet.

This project is also a system design study (see [docs/design](../design/README.md)). Agents decide the architecture and write the full reasoning in each ADR, for a reader new to system design. The owner reviews each ADR by questioning it in its review issue; the questions and answers go in the ADR's "Review" section. ADRs 0002 to 0006 predate the detailed template and are being rewritten to it.

| # | Decision | Status | Decided by |
|---|---|---|---|
| [0001](0001-monorepo-uv-pnpm.md) | Monorepo with a uv workspace and a pnpm workspace | Accepted | owner |
| [0002](0002-postgres-pgvector-hybrid-search.md) | PostgreSQL with pgvector and full-text search, no separate vector database | Accepted | agents, owner review pending |
| [0003](0003-model-provider-interfaces.md) | Every model sits behind a provider interface | Accepted | agents, owner review pending |
| [0004](0004-ingestion-queue-in-postgres.md) | Ingestion queue in Postgres (Procrastinate), no Redis | Accepted | agents, owner review pending |
| [0005](0005-application-first-then-evals.md) | Build the application first, then improve the RAG logic against an eval set | Accepted | agents, owner review pending |
| [0006](0006-better-auth.md) | Better Auth, with users in our own Postgres | Planned | agents, owner review pending |
| [0007](0007-api-web-contract.md) | The web app learns the API's shape from a generated OpenAPI file | Accepted | agents, owner review pending |
| [0008](0008-qdrant-vector-search-experiment.md) | Qdrant vector-search experiment, exit criteria fixed before any run | Proposed | agents, owner review pending |

## Template for new records

Scale the depth to the decision. A choice that is costly to reverse (a data store, a queue, a service boundary, a data model) uses every section below. A small one (a lint tool, a naming rule) needs only Context, Decision, Why and Review. Write for a reader new to system design: explain each term (HNSW, idempotency, connection pooling) the first time it appears.

```markdown
# NNNN: <decision in a few words>

**Status:** Proposed | Accepted | Planned | Superseded by NNNN

**Decided by:** agents | owner   **Review:** #<issue>, open | answered

## Context
The problem and the requirements that matter, with numbers (now and at 1000x).

## Options considered
Each real option: how it works, pros, cons, cost, what it commits us to.

## Decision
What was chosen.

## Why
The reasoning that ruled the other options out, and the assumptions it rests on.

## Consequences
What gets easier, what gets harder, what this commits us to.

## At 1000x the load
What breaks first, and what the next step would be.

## Read more
Two to four sources (docs, articles, book chapters) on the trade-off.

## Review
The owner's questions and the answers, dated, newest last. Note any change to the ADR that a question caused.
```
