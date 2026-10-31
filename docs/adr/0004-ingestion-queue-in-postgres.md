# 0004: Ingestion queue in Postgres

**Status:** Accepted

**Decided by:** agents (decided and built before study-design mode; rewritten to the full template on 2026-10-31, the decision itself unchanged)   **Review:** [#37](https://github.com/phuchaitt3/book-rag-app/issues/37), open

## Context

Uploading a book starts a long job: read the PDF, cut it into sections and chunks, and turn every chunk into a vector with the embedding model (see [ADR 0002](0002-postgres-pgvector-hybrid-search.md)). A 400-page book is about 1,000 chunks, and the embedding step calls a model server (Ollama running bge-m3), so the job takes minutes, not milliseconds. That work cannot run inside the upload request: the browser would wait, a proxy would time the request out, and a restart of the API would lose the job.

So the app needs a **job queue**: the API writes down "ingest book X" and returns at once; a separate **worker** process picks the job up, does the work, and records the result. A queue also gives retries, a limit on how many jobs run at once, and a place to see what is waiting.

A queue needs somewhere to keep the waiting jobs. The common choice is a separate broker such as Redis. This project runs on free tiers (no card for now), so every extra service is another account, another limit and another thing to keep running.

Requirements, with the numbers I assumed when this was decided (not measurements):

| | Now | At 1000x |
|---|---|---|
| Uploads | a few books per day (assumed) | thousands per day, about one every 10 to 30 seconds on average |
| Jobs waiting at once | 0 to 3 | tens to hundreds, with bursts |
| Job length | minutes, dominated by embedding (not measured yet) | the same per book |
| Failure handling | a bad PDF fails at once; a briefly unreachable model server or database is retried | the same |
| Visible state | the user can poll a job's status, stage and chunks embedded | the same |

Non-functional needs: a job must not be lost when a process restarts; two jobs for the same book must never run at the same time; the queue must not need a service we cannot run for free.

## Options considered

**A. A task queue that stores its jobs in the existing PostgreSQL database: Procrastinate (chosen).** Procrastinate is a Python library. It creates its own tables (`procrastinate_jobs` and a few more) in the same database, the API adds a row to defer a job, and one or more worker processes take rows off with `SELECT ... FOR UPDATE SKIP LOCKED` (a Postgres feature that lets many workers lock different rows without waiting for each other) and use `LISTEN/NOTIFY` (Postgres sends a message when a row is added) to wake up quickly. It has retries with a back-off, a *lock* that serialises jobs sharing a key, and periodic tasks.
- Pros: nothing new to run; the job rows survive a restart like any other data; backups and access control are the database's; no second system to keep consistent.
- Cons: the queue shares the database with the data, so queue traffic competes with query traffic; `LISTEN/NOTIFY` needs a direct connection (see "At 1000x the load"); a smaller community and fewer features than the Redis-based libraries.
- Cost: nothing extra.
- Commits us to: Postgres as the queue's ceiling, and to Procrastinate's table schema, which it migrates itself (the worker's `init` command applies it once).

**B. A task queue on Redis (arq, Taskiq, RQ, Celery with a Redis broker).** The API pushes a message to Redis; workers pull it. This is the most common setup and has the largest ecosystem.
- Pros: built for this; very high throughput; many examples and tools; a natural place for later caching or rate limiting.
- Cons: a second stateful service to run, secure, back up and pay for; Redis keeps jobs in memory unless persistence is configured, so a crash can lose jobs; "this book row exists" and "its job exists" now live in two stores and can disagree.
- Cost: another free-tier account, or a paid instance once the free limits are passed.
- Commits us to: running and monitoring Redis for as long as the app lives.

**C. A managed cloud queue (Amazon SQS, Google Cloud Tasks, or similar).** The provider runs the queue; workers poll it or receive pushes.
- Pros: no server to run; scales far beyond what we need; durable.
- Cons: needs a cloud account with a card, which this project does not have for now; couples the code to one provider; harder to run locally and in tests.
- Cost: pay per request, tiny at our volume, but needs billing set up.
- Commits us to: a cloud vendor and its credentials in every environment.

**D. Run the work inside the API process (FastAPI `BackgroundTasks`, or `asyncio.create_task`).** No queue at all.
- Pros: the least code.
- Cons: a restart or deploy loses every running job; no retries; no limit on how many run at once, so a burst of uploads starves the API of CPU and memory; no way to run it on a separate machine.
- Cost: none, but it does not meet the requirement that a job survives a restart.
- Commits us to: rewriting it as soon as any of those limits bites.

**E. A hand-written jobs table with a `SELECT ... FOR UPDATE SKIP LOCKED` loop.** Option A without the library.
- Pros: fewest dependencies; the exact behaviour is in our hands.
- Cons: we would rebuild retries, back-off, locks, stuck-job handling and periodic tasks, and those are the parts that are easy to get subtly wrong.
- Cost: our time.
- Commits us to: owning that code.

## Decision

Use Procrastinate (option A), with the jobs in the same PostgreSQL database as the data.

What is built (checked against `main`: `apps/api/src/book_rag_api/jobs.py`, `books.py`, `apps/worker/src/book_rag_worker/worker.py`, `ingest.py`, `__main__.py`; Procrastinate 3.10.0 is the version in `uv.lock`):
- `POST /books` stores the PDF, creates the book row, then calls `enqueue_ingestion`. It inserts an `ingestion_jobs` row (status `queued`) and defers the task `ingest_book` with `lock=str(book_id)`, so two jobs for the same book never run together.
- The worker is a separate process with its own image (`apps/worker/Dockerfile`), started with `python -m book_rag_worker run`. `python -m book_rag_worker init` creates the queue tables once, because Procrastinate's schema step is not safe to run twice.
- The task `ingest_book` moves the job through the stages `parse`, `chunk` and `embed` and ends with status `succeeded` or `failed` and an error message. `GET /ingestion-jobs/{id}` reads that row and counts the chunks that already have a vector.
- Only transient failures are retried: a connection error, a timeout, an HTTP 5xx or 429 from the model server, or a database `OperationalError`. They are retried with an exponential wait up to `MAX_RETRIES = 2`. A bad PDF fails at once.
- A periodic task, every 5 minutes, marks as `failed` any job that has been `queued` or `running` for over 60 minutes (`stuck_job_minutes`).

Not decided here, because no deploy exists yet: where the worker runs in production. The earlier text of this ADR said "inside the API container". The code today is a separate process with its own image, which also lets the worker scale on its own, so the production placement stays open until the deploy task (T4, blocked on D5) is done.

## Why

**Why the database as the queue (A over B and C).** At our volume the queue is tiny: a few jobs a day now, and even at 1000x about one job every 10 to 30 seconds. A Postgres queue handles that with a wide margin, so what Redis or a cloud queue offers (very high throughput) is not needed, while their costs are real: another service, and a second place where state can disagree with the database. Keeping jobs in Postgres also means a job is never lost when a process restarts, because it is a row on disk. The requirement "no extra service on a free tier" decides it when the other options are otherwise acceptable.

**Why a library and not hand-written SQL (A over E).** Retry with back-off, per-key locks, periodic tasks and crash recovery are all needed here, and each is a place for a subtle bug. Procrastinate already has them.

**Why not in-process background work (A over D).** It fails the first requirement: a job must survive a restart.

**Why a lock per book.** Two ingestion runs for one book would write duplicate sections and chunks. The lock is the cheapest way to rule that out, and the unique constraints on `(book_id, ordinal)` (migration 0002) are the second line of defence.

**Why retry only transient errors.** Retrying a corrupt PDF three times wastes minutes and hides the real error. Retrying a model server that was down for a few seconds is exactly what a queue is for.

The assumptions this rests on: the corpus stays small (see ADR 0002), embedding stays the slow part, and one Postgres is the only stateful service we run.

## Consequences

- No Redis or cloud queue to run, pay for or keep consistent with the database.
- Workers scale sideways by starting more processes that share the database; the per-book lock still holds across them.
- **The queue and the data share one database.** Heavy queue traffic and heavy search traffic compete for the same connections and disk. Not a problem now; see "At 1000x the load".
- **Enqueueing is two writes, not one transaction.** `enqueue_ingestion` commits the `ingestion_jobs` row, then defers the task through Procrastinate's own connection. If the process dies between the two, the row stays `queued` with no task behind it. Today the stuck-job sweeper turns that into `failed` after 60 minutes and the user has to upload again. The standard cure is the *transactional outbox* pattern (write the job and the "please enqueue" record in one transaction), or deferring the task on the same connection; neither is built.
- **Tied to Procrastinate's tables and its database driver.** It uses `psycopg`, while the rest of the API uses `asyncpg`, so `jobs.py` converts the connection URL (`to_libpq_dsn`). Two drivers means two sets of connection settings to keep in step.
- **Failure of the model server is not visible to the queue.** A job is retried twice and then marked `failed`; there is no dead-letter queue or alert, only the job's `error` text.

## At 1000x the load

Assume about 10,000 uploads a day instead of about 10 (a guess, not a target).

What does **not** break first: the queue itself. 10,000 jobs a day is about one job every 9 seconds, far below what a Postgres queue using `SKIP LOCKED` is generally reported to handle (thousands of jobs a second on one node; I have not measured this here).

What breaks first, in my estimate:
1. **Embedding capacity.** Each book needs about 1,000 chunk embeddings; at 10,000 books a day that is about 10 million embeddings a day, or about 115 a second, nonstop. A single Ollama instance on one machine will not do that. The next step is more model workers (a GPU pool or a hosted embedding API), and the queue needs no change for it.
2. **Job-table growth.** Procrastinate keeps finished jobs and their events in its tables. At 10,000 jobs a day the tables grow by millions of rows a year and slow the queue's own queries unless old rows are removed. Procrastinate ships a task for this (`remove_old_jobs` in its `builtin_tasks`); it is not scheduled here yet.
3. **Connections.** Every worker process holds database connections, plus one dedicated connection for `LISTEN/NOTIFY`. `LISTEN/NOTIFY` does not work through a transaction-mode connection pooler (PgBouncer, or the pooled URL a host such as Neon gives out). Procrastinate also polls, so jobs would still run, with a delay of seconds; I have not tested this. The worker should use the direct (unpooled) URL, and the settings do not yet distinguish the two.
4. **Contention with search.** Heavy ingestion writes (inserting vectors, building index entries) compete with queries for the same database. The first fix is a separate Postgres for the queue; only after that a dedicated broker.

The next step if the Postgres queue itself becomes the limit is a broker (Taskiq on Redis, option B), and the code change is contained: `jobs.py` and `worker.py` are the only places that know about Procrastinate.

## Read more

- Procrastinate documentation (concepts, locks, retries, `LISTEN/NOTIFY`, `remove_old_jobs`): https://procrastinate.readthedocs.io
- PostgreSQL documentation on `SELECT ... FOR UPDATE SKIP LOCKED` (the locking clause section of the `SELECT` page): https://www.postgresql.org/docs/current/sql-select.html
- Chris Richardson, "Transactional outbox", on writing a job and its message in one transaction: https://microservices.io/patterns/data/transactional-outbox.html

## Review

Questions and answers go here, dated, from [#37](https://github.com/phuchaitt3/book-rag-app/issues/37). None yet.
