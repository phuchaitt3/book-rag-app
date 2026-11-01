# 0004: Ingestion queue in Postgres

**Status:** Accepted   **Date:** 2026-10-30
**Decided by:** agents (before study-design mode)   **Confidence:** high
**Review:** [#37](https://github.com/phuchaitt3/book-rag-app/issues/37), open   **Study note:** [docs/design/0004-ingestion-queue-in-postgres.md](../design/0004-ingestion-queue-in-postgres.md)

## Context

Uploading a book starts a long job: read the PDF, cut it into sections and chunks, and embed every chunk (see [ADR 0002](0002-postgres-pgvector-hybrid-search.md)). A 400-page book is about 1,000 chunks and the embedding step calls a model server, so the job takes minutes. It cannot run inside the upload request: a proxy would time out and a restart of the API would lose the job. The app needs a job queue and a separate worker.

Requirements (estimates, not measurements, written 2026-10-30): a few books a day now, a few jobs waiting at once, minutes per job, dominated by embedding. A job must survive a process restart; two jobs for the same book must never run together; a bad PDF fails at once while a briefly unreachable model server or database is retried; the user can poll a job's status. The project runs on free tiers with no card, so every extra service is another account and limit.

## Options considered

- **A. Procrastinate, a Python task queue that keeps its jobs in the existing PostgreSQL.** Nothing new to run; jobs survive a restart like any row. The queue shares the database with the data, and `LISTEN/NOTIFY` needs a direct connection.
- **B. A Redis-based queue** (arq, Taskiq, Celery). The most common setup and the highest throughput. A second stateful service, jobs in memory unless persistence is set up, and job state in a second store that can disagree with the database.
- **C. A managed cloud queue** (SQS, Cloud Tasks). No server to run. Needs a cloud account with a card and ties the code to one provider.
- **D. Run the work inside the API process** (`BackgroundTasks`). The least code. A restart loses every running job, and there are no retries or limit on concurrent jobs.
- **E. A hand-written jobs table with a `SKIP LOCKED` loop.** Fewest dependencies. We would rebuild retries, locks and stuck-job handling, which are easy to get subtly wrong.

The full comparison is in the study note.

## Decision

Use Procrastinate (option A), with the jobs in the same PostgreSQL database as the data. `POST /books` stores the PDF, inserts an `ingestion_jobs` row (status `queued`) and defers the task `ingest_book` with `lock=str(book_id)`. A separate worker process (`python -m book_rag_worker run`, its own image) moves the job through `parse`, `chunk` and `embed` and ends it `succeeded` or `failed`. Only transient failures (connection error, timeout, HTTP 5xx or 429, database `OperationalError`) are retried, with exponential wait, at most twice. A periodic task marks jobs stuck `queued` or `running` for over 60 minutes as `failed`. Where the worker runs in production stays open until the deploy task (T4).

## Why

At our volume the queue is tiny, so Redis's throughput is not needed while its costs are real: another service and a second place where state can disagree with the database. A row on disk is never lost when a process restarts. No extra service on a free tier decides it when the options are otherwise acceptable. A library rather than hand-written SQL (E), because retries, per-key locks, periodic tasks and crash recovery each hide a subtle bug and Procrastinate already has them. Not in-process (D), because it fails the restart requirement.

The lock per book stops two runs from writing duplicate chunks; the unique constraints on `(book_id, ordinal)` are the second line of defence. Only transient errors are retried because retrying a corrupt PDF wastes minutes and hides the real error.

The decision rests on these assumptions: the corpus stays small (ADR 0002), embedding stays the slow part, and one Postgres is the only stateful service we run. It would change if queue traffic starts to compete with search for the database, or if the queue needs a feature Procrastinate lacks.

## Consequences

- No Redis or cloud queue to run, pay for or keep consistent. Workers scale sideways by starting more processes; the per-book lock holds across them.
- The queue and the data share one database, so heavy ingestion and heavy search compete for connections and disk.
- Enqueueing is two writes, not one transaction: the `ingestion_jobs` row commits, then the task is deferred. A crash between them leaves a `queued` row with no task; the sweeper marks it `failed` after 60 minutes and the user uploads again. The transactional outbox pattern would cure it and is not built.
- Procrastinate uses `psycopg` and the API uses `asyncpg`, so `jobs.py` converts the URL (`to_libpq_dsn`): two sets of connection settings.
- A book is searchable only after its latest job succeeded (decided 2026-10-31, [#81](https://github.com/phuchaitt3/book-rag-app/issues/81)): the worker commits embeddings in batches of 32, so until the last batch a search would use part of the book. The chat endpoint answers `409 Conflict`, naming the job's state, unless the latest job is `succeeded`.
- A model-server outage is retried twice, then the job is `failed`; there is no dead-letter queue or alert, only the job's `error` text.
- Next steps as load grows, in order: more embedding capacity (the first limit, not the queue); a scheduled `remove_old_jobs` for table growth; a direct, unpooled URL for the worker; a separate Postgres for the queue; only then a broker (option B, contained in `jobs.py` and `worker.py`). The analysis is in the study note.

## Change log

- 2026-10-31: rewritten to the full template with options, consequences and the 1000x analysis ([#37](https://github.com/phuchaitt3/book-rag-app/issues/37)).
- 2026-10-31: a book is searchable only after its latest job succeeded; chat answers 409 otherwise ([#81](https://github.com/phuchaitt3/book-rag-app/issues/81)).
- 2026-11-01: rewritten to the short template; terms, options in depth and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
