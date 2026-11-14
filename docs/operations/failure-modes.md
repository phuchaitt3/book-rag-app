# Ingestion failure modes

What happens to an ingestion job ([ADR 0004](../adr/0004-ingestion-queue-in-postgres.md)) when something goes wrong, and the test that proves it. All tests are in [apps/worker/tests/test_ingest_failures.py](../../apps/worker/tests/test_ingest_failures.py) (testcontainers Postgres, the fake embedder's injected errors) and run in the default CI test job.

| Failure | Expected behaviour | Test |
| --- | --- | --- |
| Worker killed mid-embedding (after some batches are committed) | The job stays `running` with half the vectors. The 5-minute sweep fails it after `stuck_job_minutes` with `stuck: no progress ...`; a new upload (new job) replaces the partial rows: every ordinal once, no chunk without a vector. | `test_a_killed_worker_leaves_partial_chunks_and_a_new_run_completes_them` |
| Same job delivered again to a new worker after a kill | The second run deletes the first run's sections and chunks and embeds again: no duplicates, status `succeeded`. | `test_a_stalled_job_picked_up_again_by_a_new_worker_finishes_cleanly` |
| Embedder fails transiently (connection error, timeout, HTTP 5xx or 429) | Job goes back to `queued` with `retrying after ...`, the queue waits with exponential backoff, at most `MAX_RETRIES` (2) retries; then `succeeded` with no duplicate or missing chunks. | `test_transient_embedder_failures_back_off_then_succeed` |
| Transient error that never clears | After the retries the job is `failed` with the error text. | `test_a_transient_error_that_never_clears_fails_after_the_retries` (in `test_ingestion.py`) |
| Embedder fails permanently (HTTP 4xx, bad value) | Job is `failed` at once, `error` holds the exception type and message, the queue runs it exactly once. `GET /ingestion-jobs/{id}` returns both. | `test_a_permanent_embedder_error_fails_once_and_the_api_shows_why` |
| Unreadable PDF | `failed` at once, not retried. | `test_a_bad_pdf_fails_at_once_without_retrying` (in `test_ingestion.py`) |
| Two workers race for one job | Postgres `FOR UPDATE SKIP LOCKED` hands it to one worker; the other finds nothing. The embedder is called once per batch, not twice. | `test_two_workers_racing_for_one_job_run_it_once` |
| Two jobs for one book | The per-book lock runs them one after the other. | `test_two_jobs_for_one_book_both_finish` (in `test_ingestion.py`) |
| Job stuck `queued` or `running` | The sweep fails it; fresh and finished jobs are untouched. | `test_the_sweep_fails_old_unfinished_jobs_only` (in `test_ingestion.py`) |

Known gaps: the kill is simulated by cancelling the worker task, not by killing a process, and the stalled-job re-delivery is simulated by calling `run_ingestion` again with the same job id rather than waiting for Procrastinate's stalled-job detection.
