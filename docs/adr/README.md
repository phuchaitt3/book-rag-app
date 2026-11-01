# Architecture decision records

Records of choices that are costly to reverse. Each states the context, the options, the decision, the reasoning and its consequences. *Accepted* means decided and in use; *Planned* means decided but not built yet.

This project is also a system design study (see [docs/design](../design/README.md)). Agents decide the architecture and record it here, following the `workflow:adr` skill. An ADR is short (about two pages) and starts with the decision. The material for studying it goes in a linked study note in `docs/design/`: terms explained for a reader new to system design, options in depth, what breaks at 1000x the load, and sources to read. The owner reviews each ADR by questioning it in its review issue. The questions and answers stay in the issue, and each change they cause gets one dated line in the ADR's change log. (standard: Nygard 2011, "one or two pages"; Azure Well-Architected, "avoid making decision records design guides"; checked 2026-11-01)

ADRs written before 2026-11-01 are being rewritten to this template, one PR per ADR. The decision stays the same, the study material moves to a note, and the Review section is replaced by a change log.

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

About two pages, change log excluded. A small decision (a lint tool, a naming rule) needs only Context, Decision, Why and the change log. One decision per record. Once a record is accepted, a changed decision is a new ADR that supersedes it. A clarification or new measurement that leaves the decision unchanged gets a dated change-log line and the smallest edit to the body.

```markdown
# NNNN: <the decision, in a few words>

**Status:** Proposed | Accepted | Planned | Superseded by NNNN | Rejected   **Date:** YYYY-MM-DD
**Decided by:** agents | owner   **Confidence:** high | medium | low
**Review:** #<issue>, open | answered   **Study note:** [docs/design/NNNN-<slug>.md](../design/NNNN-<slug>.md)

## Context
The forces, stated neutrally: the problem, requirements with numbers (marked measured or estimated, with the date), constraints.

## Options considered
Each real option in two to four lines: what it is, its main pro and con. The full comparison is in the study note.

## Decision
One to three sentences.

## Why
Why this option beat the others, and the assumptions that would change the answer.

## Consequences
Good, bad and neutral; follow-up decisions; known gaps as one line with an issue link; the next step as load grows (one line each; the full "At 1000x the load" analysis is in the study note).

## Change log
Dated one-line entries, newest last, each with the issue or PR that caused it.
```
