# Runbook

One entry per alert in [alerts.yml](alerts.yml). Targets: [slo.md](slo.md). The local stack: `docker compose -f compose.yaml -f compose.observability.yaml up -d`, then Prometheus at http://127.0.0.1:9090 and Grafana at http://127.0.0.1:3001 (dashboard "Book RAG"). API logs are JSON with a request ID; the `X-Request-ID` of a failing request finds its log lines (`docker compose logs api`).

## ChatAvailabilityFastBurn

**Symptom.** Page. Chat requests answer 5xx fast enough to spend 2% of the monthly budget in an hour.
**Likely causes.** The database is down (also `ReadinessFailing`); the answer model (Ollama or a hosted provider) is down or out of memory; an API deploy broke the chat route.
**Checks.** Dashboard panel "Chat error rate". `curl -s 127.0.0.1:8000/readyz`. `docker compose logs api --since 15m` for the stack trace behind the 500s. `curl -s $OLLAMA_URL/api/tags` for the model server.
**Fix.** Restore the dependency that fails (restart the database or model server). If a deploy caused it, roll back to the previous image. Confirm the 5m error rate returns to zero before closing.

## ChatAvailabilitySlowBurn

**Symptom.** Ticket. A lower error rate (6x budget burn over 6 hours) that would exhaust the budget in 5 days.
**Likely causes.** An intermittent failure: a flaky model server, a rare input that raises, connection pool exhaustion.
**Checks.** Same as the fast burn; group the 5xx by time and look for one repeated message in the logs.
**Fix.** Fix the repeated error, with a regression test. If it is a dependency, add or tune its timeout and retry.

## ChatLatencyFastBurn

**Symptom.** Page. Most chat answers take over 30 s (the benchmark's p90 is 13.2 s with the reranker).
**Likely causes.** The answer model was unloaded and is loading (cold start 22 s for the 3B model, 127 s for the 7B, see serving-latency.md "Cold start"); the 7B model and the embedder swap on a small GPU (about 47 s per switch); the reranker is slow or hanging.
**Checks.** Dashboard panel "Retrieval latency by stage": if `rerank` or `embed` is slow the cause is before the model. `ollama ps` for what is loaded. `nvidia-smi` for GPU memory.
**Fix.** Use the 3B model (`LLM_MODEL=qwen2.5:3b-instruct`) or turn the reranker off (`RERANKER_PROVIDER=none`) on a 6 GB card; raise `OLLAMA_KEEP_ALIVE`; warm the model with one request after a restart.

## ChatLatencySlowBurn

**Symptom.** Ticket. A smaller share of slow answers (6x budget burn over 6 hours).
**Likely causes.** Idle spells that let the model unload (the default keep-alive is 5 minutes), long passages, a shared GPU.
**Checks.** Does slowness follow idle gaps? Compare the stage histograms with the benchmark.
**Fix.** Longer keep-alive. If the target no longer fits the hardware, change it in slo.md with a new measurement, not by silencing the alert.

## RetrievalSlow

**Symptom.** Ticket. Over 30% of questions need more than 5 s before the citations (benchmark p90: 2.97 s with the reranker, 0.16 s without).
**Likely causes.** The reranker is slow (depth 20 on CPU took about 58 s per question); the vector store or Postgres is slow or large; the embedder is swapping.
**Checks.** Dashboard panel "Retrieval latency by stage" shows which of `embed`, `search`, `rerank` grew.
**Fix.** Reranker on GPU or off; check database load and indexes; reload the embedding model.

## RerankerFallbackRateHigh

**Symptom.** Ticket. Over 10% of questions were answered in the fused order because the reranker failed. Users see no error, only lower ranking quality.
**Likely causes.** The TEI reranker container is down, still downloading its model on first start, or crash-looping (the tokenizer panic noted in `compose.reranker.yaml`, #198).
**Checks.** The `reason` label of `rerank_fallbacks_total` (query `sum by (reason) (rate(rerank_fallbacks_total[15m]))`); `docker compose logs reranker`.
**Fix.** Restart the reranker; if it panics on its volume, follow the recovery steps in `compose.reranker.yaml`. If the reranker is not wanted, set `RERANKER_PROVIDER=none` so the fallback stops being counted.

## ReadinessFailing

**Symptom.** Page. `/readyz` answers 503: the database does not answer.
**Likely causes.** The database is down, unreachable, out of connections, or out of disk.
**Checks.** `curl -s 127.0.0.1:8000/readyz` (the body says `database: down`); `docker compose ps db`; database logs.
**Fix.** Restart or restore the database; check its disk and connection limit. Liveness (`/healthz`) stays 200 on purpose, so do not restart the API for this.

## ApiTargetDown

**Symptom.** Page. Prometheus cannot scrape the API (`up == 0`).
**Likely causes.** The API process is down or crash-looping; its port is not reachable from Prometheus; the scrape target in `prometheus.yml` is wrong.
**Checks.** `curl -s 127.0.0.1:8000/healthz`; the Prometheus "Status, Targets" page for the scrape error; `docker compose ps api`.
**Fix.** Start or fix the API; correct the target address. Alerts based on API metrics stay silent while the target is down, so treat this one first.

## IngestionUploadErrors

**Symptom.** Ticket. More than 20% of `POST /books` uploads answer 5xx. There is no metric for a stuck job (slo.md, "What the metrics cannot show yet"), so this is the proxy.
**Likely causes.** Object storage (S3) or the database is unavailable; the file store is full.
**Checks.** API logs for the 5xx. For stuck jobs, ask the database: select the rows of `ingestion_jobs` whose status is not a final one (status names in `apps/api/src/book_rag_api/models.py`), oldest first, and call `GET /ingestion-jobs/{job_id}` on them.
**Fix.** Restore the dependency; re-upload the failed books. Jobs that stay unfinished after the cause is gone need re-queuing by hand.
