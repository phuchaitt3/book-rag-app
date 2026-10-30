# 0004: Ingestion queue in Postgres

**Status:** Planned

## Context
Parsing, chunking and embedding a book is slow and must stay off the request path. A conventional queue (arq, Taskiq) needs Redis, which is one more service on a free tier.

## Decision
Use Procrastinate, a task queue on PostgreSQL. Locally the worker is a separate process; in production it runs inside the API container.

## Consequences
- No Redis service to run or pay for.
- Workers scale horizontally by adding processes that share the database.
- Throughput is bounded by Postgres; if that becomes the limit, a dedicated broker (Taskiq on Redis) is the next step.
