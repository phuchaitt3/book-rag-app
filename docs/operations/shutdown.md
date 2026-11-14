# Shutdown and client disconnects

How the API and the worker behave on a deploy, a scale-in or a closed browser tab (#228). Both exit with status 0.

## Client disconnect (chat)

When the client closes the connection mid-answer, the server cancels the response. The chat generator catches the cancellation, which closes the model stream, so the model call stops and no more tokens are generated or billed. Each one is counted in `chat_client_disconnects_total` (served at `/metrics`). A steady rise means users leave before answers finish: look at the latency panels first.

## API (SIGTERM)

1. The server stops accepting new connections.
2. The lifespan shutdown marks the process as draining (`/readyz` answers 503) and waits up to `SHUTDOWN_DRAIN_TIMEOUT` seconds (default 20) for answers still streaming.
3. It logs a warning with the number of streams still running if the time ran out, then closes the Qdrant client and the database pool.

Set uvicorn's `--timeout-graceful-shutdown` to the same value, or higher, so the server does not cut streams before the lifespan waits for them, and keep both under the platform's termination grace period (Kubernetes: 30 s by default). The Dockerfile start command is deploy config and is not changed by this setting.

## Worker (SIGTERM or Ctrl+C)

The ingestion queue is Procrastinate on Postgres ([ADR 0004](../adr/0004-ingestion-queue-in-postgres.md)). On SIGTERM the worker:

1. takes no new job;
2. lets the running job finish for up to `SHUTDOWN_TIMEOUT` seconds (default 20);
3. if the job is still running, cancels it, sets its `ingestion_jobs` row back to `queued` (with an error text saying it was interrupted) and returns the queue job to `todo` at once, without backoff;
4. closes its pools and exits 0.

Another worker (or the restarted one) picks the job up and runs it again; a re-run replaces what the interrupted run stored, so nothing is duplicated, and the book stays unsearchable until the latest job succeeds. A shutdown retry does not count as a failure.

SIGKILL, an out-of-memory kill or a power loss gives the worker no chance to do this. The job stays `running` until the stuck-job sweep fails it after `STUCK_JOB_MINUTES` (60 minutes; ADR 0004), and the user uploads the book again.

On Windows only Ctrl+C reaches the worker (SIGTERM is not delivered to Python there); the same code path runs. Tests set the stop event directly and send no signal.
