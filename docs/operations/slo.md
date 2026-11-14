# Service level objectives (#226)

What "healthy" means for the API, in numbers, and the metric behind each. The metrics are the ones the API exports at `/metrics` ([ADR 0010](../adr/), `apps/api/src/book_rag_api/metrics.py`). Alert rules: [alerts.yml](alerts.yml). What to do when one fires: [runbook.md](runbook.md).

**Where the numbers come from.** [docs/benchmarks/serving-latency.md](../benchmarks/serving-latency.md) measured the chat endpoint on one laptop, one user at a time, 30 questions per arm, with the reranker on: retrieval (the `citations` event) median 2.80 s, p90 2.97 s; first token median 10.69 s, p90 11.88 s; whole answer median 11.57 s, p90 13.18 s. The targets below sit at about 1.7x (retrieval and first token) and 2.3x (whole answer) that p90, on the next histogram bucket edge, because a histogram quantile cannot be finer than its buckets (`REQUEST_BUCKETS`, `STAGE_BUCKETS` and `FIRST_TOKEN_BUCKETS` in `metrics.py`). They are targets for that local setup. Production would call hosted models (ADR 0003) and has not been measured, so revisit them with the first production measurement. The benchmark has no concurrency and no error injection, so the availability targets are stated goals, not measured values.

## SLOs

Window: 30 days, rolling. The chat route label is `/books/{book_id}/chat`.

| # | SLO | Target | Error budget (30 days) | SLI metric |
|---|---|---|---|---|
| 1 | Chat availability: share of chat requests that do not end in a 5xx | 99% | 1% of requests; at 1 request per minute, about 432 failed requests | `http_request_duration_seconds_count{route="/books/{book_id}/chat"}`, split by the `status` label |
| 2 | Chat answer latency: share of chat requests whose whole answer is sent within 30 s | 95% | 5% of requests may be slower | `http_request_duration_seconds_bucket{route="/books/{book_id}/chat",le="30"}` over `_count`. The histogram runs to the last streamed byte, so this is the whole answer. Benchmark p90: 13.18 s. |
| 3 | Retrieval latency (time to the citations): share of questions retrieved within 5 s | 95% | 5% of questions | `retrieval_duration_seconds_bucket{le="5"}` over `_count`. Benchmark p90: 2.97 s with the reranker, 0.16 s without. |
| 4 | Readiness: share of `/readyz` probes that answer 200 | 99.5% | 0.5% of probes | `http_request_duration_seconds_count{route="/readyz"}`, split by `status` (503 means the database does not answer) |
| 5 | First token latency: share of model answers whose first token is streamed within 20 s of the request | 95% | 5% of answers | `chat_first_token_duration_seconds_bucket{le="20"}` over `_count`. Time from request start (so it includes retrieval) to the first `token` event; abstained replies, which skip the model, are not counted. Benchmark p90: 11.88 s with the reranker, 8.93 s without. |

A 4xx is the caller's fault and does not count against SLO 1 (a rate-limited chat returns 429, [#193](https://github.com/phuchaitt3/book-rag-app/issues/193)).

## Ingestion jobs

The API reads the `ingestion_jobs` table at each scrape (all owners) and exports `ingestion_jobs{status}` (queued, running, succeeded, failed), `ingestion_oldest_queued_age_seconds` and `ingestion_oldest_running_age_seconds`. There is no SLO target for ingestion; the alert `IngestionStuck` fires when a job waits over 15 minutes or runs over an hour, and the dashboard panel "Ingestion queue depth" shows the counts. If the table cannot be read at scrape time the gauges are left out and `/metrics` still answers. The upload route's 5xx rate is alerted separately (`IngestionUploadErrors`).

## Alerting

Burn rate is the error rate divided by the budget rate. A burn rate of 1 uses the whole budget in exactly 30 days. Following the multi-window pattern in the Google SRE Workbook, "Alerting on SLOs" (checked 2026-11-15), a page needs a long and a short window both above the threshold, so a finished incident stops alerting quickly:

| Severity | Burn rate | Long window | Short window | Budget used if it lasts |
|---|---|---|---|---|
| page | 14.4 | 1 h | 5 min | 2% in 1 h |
| ticket | 6 | 6 h | 30 min | 5% in 6 h |

At this project's traffic (a demo), one failed request could trip a burn alert; each burn rule also requires at least 5 requests in its short window.
