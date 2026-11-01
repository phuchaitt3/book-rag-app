# Study note: ingestion queue in Postgres

**For:** [ADR 0004](../adr/0004-ingestion-queue-in-postgres.md)   **Status:** decided in ADR 0004

This note holds the teaching material behind ADR 0004. The ADR states the decision; this note explains the terms, compares the options in depth and works through what breaks at 1000x the load. It was moved out of the ADR on 2026-11-01 (#128); the text is the ADR's earlier wording, lightly trimmed.

## Problem

Uploading a book starts a long job: read the PDF, cut it into sections and chunks, and turn every chunk into a vector with the embedding model. A 400-page book is about 1,000 chunks, and the embedding step calls a model server (Ollama running bge-m3), so the job takes minutes, not milliseconds. That work cannot run inside the upload request: the browser would wait, a proxy would time the request out, and a restart of the API would lose the job.

## Terms

- **Job queue.** The API writes down "ingest book X" and returns at once; a separate **worker** process picks the job up, does the work and records the result. A queue also gives retries, a limit on how many jobs run at once, and a place to see what is waiting.
- **Broker.** The service that holds waiting jobs. The common choice is Redis.
- **`SELECT ... FOR UPDATE SKIP LOCKED`.** A Postgres feature that lets many workers lock different rows without waiting for each other, so each takes a different job.
- **`LISTEN/NOTIFY`.** Postgres sends a message to listening connections when a row is added, so a worker wakes up quickly instead of polling.
- **Lock (Procrastinate).** Jobs that share a lock key never run at the same time.
- **Transactional outbox.** Write the job and the "please enqueue" record in one database transaction, so neither can exist without the other.
- **Dead-letter queue.** A place where jobs that failed every retry are kept for inspection.

## Requirements

Numbers assumed when this was decided (not measurements).

| | Now | At 1000x |
|---|---|---|
| Uploads | a few books per day | thousands per day, about one every 10 to 30 seconds on average |
| Jobs waiting at once | 0 to 3 | tens to hundreds, with bursts |
| Job length | minutes, dominated by embedding (not measured yet) | the same per book |
| Failure handling | a bad PDF fails at once; a briefly unreachable model server or database is retried | the same |
| Visible state | the user can poll a job's status, stage and chunks embedded | the same |

Non-functional needs: a job must not be lost when a process restarts; two jobs for the same book must never run at the same time; the queue must not need a service we cannot run for free.

## Options in depth

**A. Procrastinate on the existing PostgreSQL (chosen).** A Python library. It creates its own tables (`procrastinate_jobs` and a few more) in the same database; the API adds a row to defer a job, and one or more worker processes take rows off with `SKIP LOCKED` and wake on `LISTEN/NOTIFY`. It has retries with back-off, a lock that serialises jobs sharing a key, and periodic tasks.
- Pros: nothing new to run; job rows survive a restart; backups and access control are the database's; no second system to keep consistent.
- Cons: queue traffic competes with query traffic; `LISTEN/NOTIFY` needs a direct connection; a smaller community and fewer features than the Redis-based libraries.
- Commits us to: Postgres as the queue's ceiling, and Procrastinate's table schema, which it migrates itself (the worker's `init` command applies it once).

**B. A task queue on Redis (arq, Taskiq, RQ, Celery with a Redis broker).** The API pushes a message to Redis; workers pull it.
- Pros: built for this; very high throughput; many examples and tools; a natural place for later caching or rate limiting.
- Cons: a second stateful service to run, secure, back up and pay for; Redis keeps jobs in memory unless persistence is configured, so a crash can lose jobs; "this book row exists" and "its job exists" live in two stores and can disagree.
- Commits us to: running and monitoring Redis for as long as the app lives.

**C. A managed cloud queue (Amazon SQS, Google Cloud Tasks).**
- Pros: no server to run; scales far beyond what we need; durable.
- Cons: needs a cloud account with a card, which this project does not have for now; couples the code to one provider; harder to run locally and in tests.
- Commits us to: a cloud vendor and its credentials in every environment.

**D. Run the work inside the API process (`BackgroundTasks`, `asyncio.create_task`).**
- Pros: the least code.
- Cons: a restart or deploy loses every running job; no retries; no limit on how many run at once, so a burst of uploads starves the API of CPU and memory; cannot run on a separate machine.
- Commits us to: rewriting it as soon as any of those limits bites.

**E. A hand-written jobs table with a `SKIP LOCKED` loop.** Option A without the library.
- Pros: fewest dependencies; exact behaviour in our hands.
- Cons: we would rebuild retries, back-off, locks, stuck-job handling and periodic tasks, the parts that are easy to get subtly wrong.
- Commits us to: owning that code.

## What is built

Checked against `main` on 2026-11-01: `apps/api/src/book_rag_api/jobs.py`, `books.py`, `apps/worker/src/book_rag_worker/worker.py`, `ingest.py`, `__main__.py`; Procrastinate 3.10.0 is the version in `uv.lock`.

- `POST /books` stores the PDF, creates the book row, then calls `enqueue_ingestion`, which inserts an `ingestion_jobs` row (status `queued`) and defers `ingest_book` with `lock=str(book_id)`.
- The worker is a separate process with its own image (`apps/worker/Dockerfile`). `python -m book_rag_worker init` creates the queue tables once, because Procrastinate's schema step is not safe to run twice.
- `ingest_book` moves the job through `parse`, `chunk` and `embed` and ends with `succeeded` or `failed` and an error message. `GET /ingestion-jobs/{id}` reads that row and counts the chunks that already have a vector.
- Retries: connection error, timeout, HTTP 5xx or 429 from the model server, or a database `OperationalError`; exponential wait, `MAX_RETRIES = 2`. A bad PDF fails at once.
- A periodic task, every 5 minutes, marks as `failed` any job `queued` or `running` for over 60 minutes (`stuck_job_minutes`).
- The earlier text of the ADR said the worker runs "inside the API container". The code is a separate process with its own image, which also lets the worker scale on its own, so production placement stays open until the deploy task (T4, blocked on D5).

## Measurements

None. The 1000x figures below are estimates to be measured, not results.

## At 1000x the load

Assume about 10,000 uploads a day instead of about 10 (a guess, not a target).

What does **not** break first: the queue itself. 10,000 jobs a day is about one job every 9 seconds, far below what a Postgres queue using `SKIP LOCKED` is generally reported to handle (thousands of jobs a second on one node; not measured here).

What breaks first, in estimated order:
1. **Embedding capacity.** Each book needs about 1,000 chunk embeddings; at 10,000 books a day that is about 10 million a day, about 115 a second, nonstop. A single Ollama instance on one machine will not do that. The next step is more model workers (a GPU pool or a hosted embedding API); the queue needs no change.
2. **Job-table growth.** Procrastinate keeps finished jobs and their events. At 10,000 jobs a day the tables grow by millions of rows a year and slow the queue's own queries unless old rows are removed. Procrastinate ships a task for this (`remove_old_jobs` in its `builtin_tasks`); it is not scheduled here yet.
3. **Connections.** Every worker process holds database connections, plus one dedicated connection for `LISTEN/NOTIFY`, which does not work through a transaction-mode pooler (PgBouncer, or the pooled URL a host such as Neon gives out). Procrastinate also polls, so jobs would still run, with a delay of seconds (not tested). The worker should use the direct (unpooled) URL; the settings do not yet distinguish the two.
4. **Contention with search.** Heavy ingestion writes (vectors, index entries) compete with queries for the same database. The first fix is a separate Postgres for the queue; only after that a dedicated broker.

If the Postgres queue itself becomes the limit, the next step is a broker (Taskiq on Redis, option B). The change is contained: `jobs.py` and `worker.py` are the only places that know about Procrastinate.

## Read more

- [Procrastinate documentation](https://procrastinate.readthedocs.io): concepts, locks, retries, `LISTEN/NOTIFY`, `remove_old_jobs`.
- [PostgreSQL `SELECT` page](https://www.postgresql.org/docs/current/sql-select.html): the locking clause section covers `FOR UPDATE SKIP LOCKED`.
- Chris Richardson, [Transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html): writing a job and its message in one transaction.
