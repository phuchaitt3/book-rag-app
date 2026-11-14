# Service level objectives (#226)

What "healthy" means for the API, in numbers, and the metric behind each. The metrics are the ones the API exports at `/metrics` ([ADR 0010](../adr/), `apps/api/src/book_rag_api/metrics.py`). Alert rules: [alerts.yml](alerts.yml). What to do when one fires: [runbook.md](runbook.md).

**Where the numbers come from.** [docs/benchmarks/serving-latency.md](../benchmarks/serving-latency.md) measured the chat endpoint on one laptop, one user at a time, 30 questions per arm, with the reranker on: retrieval (the `citations` event) median 2.80 s, p90 2.97 s; whole answer median 11.57 s, p90 13.18 s. The targets below sit at about 1.7x (retrieval) and 2.3x (whole answer) that p90, on the next histogram bucket edge, because a histogram quantile cannot be finer than its buckets (`REQUEST_BUCKETS` and `STAGE_BUCKETS` in `metrics.py`). They are targets for that local setup. Production would call hosted models (ADR 0003) and has not been measured, so revisit them with the first production measurement. The benchmark has no concurrency and no error injection, so the availability targets are stated goals, not measured values.

## SLOs

Window: 30 days, rolling. The chat route label is `/books/{book_id}/chat`.

| # | SLO | Target | Error budget (30 days) | SLI metric |
|---|---|---|---|---|
| 1 | Chat availability: share of chat requests that do not end in a 5xx | 99% | 1% of requests; at 1 request per minute, about 432 failed requests | `http_request_duration_seconds_count{route="/books/{book_id}/chat"}`, split by the `status` label |
| 2 | Chat answer latency: share of chat requests whose whole answer is sent within 30 s | 95% | 5% of requests may be slower | `http_request_duration_seconds_bucket{route="/books/{book_id}/chat",le="30"}` over `_count`. The histogram runs to the last streamed byte, so this is the whole answer. Benchmark p90: 13.18 s. |
| 3 | Retrieval latency (time to the citations): share of questions retrieved within 5 s | 95% | 5% of questions | `retrieval_duration_seconds_bucket{le="5"}` over `_count`. Benchmark p90: 2.97 s with the reranker, 0.16 s without. |
| 4 | Readiness: share of `/readyz` probes that answer 200 | 99.5% | 0.5% of probes | `http_request_duration_seconds_count{route="/readyz"}`, split by `status` (503 means the database does not answer) |

A 4xx is the caller's fault and does not count against SLO 1 (a rate-limited chat returns 429, [#193](https://github.com/phuchaitt3/book-rag-app/issues/193)).

## What the metrics cannot show yet

- **Time to first token** has no metric: the benchmark measures it from the client (`experiments/serving/measure.py`), and the server histogram only times the whole stream. The first token takes about 8 to 11 s, almost all of it the model reading the passages, so SLO 2 is the closest server-side view. A first-token histogram is a candidate follow-up.
- **Ingestion jobs** (the `ingestion_jobs` table) have no metric, so there is no alert for a stuck job and no queue-depth panel. What exists is the 5xx rate of the upload route (`POST /books`), alerted in [alerts.yml](alerts.yml). A gauge of jobs by status would close this gap; see the runbook entry `IngestionUploadErrors` for the manual check.

## Alerting

Burn rate is the error rate divided by the budget rate. A burn rate of 1 uses the whole budget in exactly 30 days. Following the multi-window pattern in the Google SRE Workbook, "Alerting on SLOs" (checked 2026-11-15), a page needs a long and a short window both above the threshold, so a finished incident stops alerting quickly:

| Severity | Burn rate | Long window | Short window | Budget used if it lasts |
|---|---|---|---|---|
| page | 14.4 | 1 h | 5 min | 2% in 1 h |
| ticket | 6 | 6 h | 30 min | 5% in 6 h |

At this project's traffic (a demo), one failed request could trip a burn alert; each burn rule also requires at least 5 requests in its short window.
