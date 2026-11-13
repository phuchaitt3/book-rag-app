# 0010: The API serves Prometheus metrics at /metrics; retrieval reports through an observer

**Status:** Accepted   **Date:** 2026-11-13
**Decided by:** agents   **Confidence:** medium
**Review:** [#194](https://github.com/phuchaitt3/book-rag-app/issues/194), open   **Study note:** [docs/design/0010-metrics-endpoint.md](../design/0010-metrics-endpoint.md)

## Context

The API has `/healthz` and `/readyz` and logs, and no numbers. [ADR 0009](0009-reranker-local-tei-service.md) made reranker failure silent by design (the fused order is returned), so a reranker that is always down shows only in logs ([#187](https://github.com/phuchaitt3/book-rag-app/issues/187)). Retrieval has three steps of very different cost (query embedding, search, rerank; the rerank is about 2.6 s at p50 on the local GPU, measured 2026-11-10) and no live view of any of them. Scalability and operability are this project's first goal.

## Options considered

- **`prometheus-client`, pull `/metrics`.** One small dependency, the standard text format, readable with `curl`. Per-process numbers need care with several workers.
- **OpenTelemetry SDK with OTLP push.** Metrics, traces and logs in one model, but several packages and a collector even for local use; the traces are not needed for this task.
- **Hand-written JSON counters.** No dependency, but a format no tool reads.
- **A per-answer fallback flag in the stream.** Changes the API contract and gives no rates.

## Decision

Add `prometheus-client` and serve `GET /metrics` (not in the OpenAPI document) from a per-app registry. Metrics: `http_request_duration_seconds{method,route,status}` (histogram, to the last byte, route template as label), `retrieval_duration_seconds` (histogram), `retrieval_stage_duration_seconds{stage=embed|search|rerank}` (histogram) and `rerank_fallbacks_total{reason=timeout|error}` (counter). `HybridRetriever` takes an optional observer; the API's Prometheus implementation is the only code that names the library.

## Why

It is the smallest thing that answers both questions (which step is slow, is the reranker down) with the format monitoring tools already read. The observer keeps `packages/rag` free of a metrics dependency and testable with a fake, like the provider interfaces in [ADR 0003](0003-model-provider-interfaces.md). Labels come only from fixed sets (route templates, stage, reason), so series count does not grow with traffic. A per-app registry stops tests that build several apps from clashing on global metric names.

The answer would change if traces are wanted (move to OpenTelemetry; a Collector can still read this endpoint, and the observer is the only code to change), or if the API runs several processes per container (use `prometheus-client` multiprocess mode, or one process per container).

## Consequences

- An always-down reranker is one query: `rate(rerank_fallbacks_total[5m]) > 0`. No alert rule or dashboard ships yet; a local Prometheus and Grafana in Compose are a follow-up.
- `/metrics` is unauthenticated, like `/healthz`: in production only the scraper may reach it (deployment item).
- The worker has no HTTP server, so ingestion has no metrics yet (follow-up, queue depth and job duration).
- The request histogram's route label makes unknown paths one `unmatched` series by design.
- Next step as load grows: multiprocess mode or one process per container, then recording rules for percentiles.

## Change log

- 2026-11-13: accepted with the code in [#192](https://github.com/phuchaitt3/book-rag-app/issues/192), part of [#187](https://github.com/phuchaitt3/book-rag-app/issues/187).
