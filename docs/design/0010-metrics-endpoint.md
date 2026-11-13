# Study note: how the API exposes latency and reranker-fallback numbers

**For:** ADR 0010   **Status:** decided in ADR 0010

## Problem

The API logs a warning when the reranker fails and returns the fused order ([ADR 0009](../adr/0009-reranker-local-tei-service.md)). Nothing counts it, and no one can say how long retrieval, the embedding call or the rerank take in a running system; the benchmarks measure them only in offline scripts. Operability comes before features in this project, so the running API must answer "is it slow, and which step?" and "is the reranker silently down?" without reading logs.

## Terms

- **Metric:** a number a running process keeps and a monitoring system reads over time. **Counter:** only goes up (requests served, fallbacks). **Histogram:** counts observations into latency buckets, so a server can compute percentiles later (p50, p95) from the counts.
- **Percentile (p95):** the latency that 95% of requests beat. Averages hide the slow tail, which is what users notice.
- **Pull and push:** in the pull model the process serves its numbers on an HTTP path and a scraper (Prometheus) fetches them every few seconds. In the push model the process sends them to a collector.
- **Prometheus text format:** the plain-text format a pull endpoint serves; many tools read it.
- **Cardinality:** the number of distinct label combinations. Each combination is a separate time series that costs memory in the scraper, so a label such as a user id or a raw URL path (`/books/<uuid>/chat`) grows without bound.
- **RED:** Rate, Errors, Duration, the three numbers to keep for every request-serving service.

## Requirements

- Request duration and status per route (RED). Needed; estimated cost: one histogram.
- Retrieval latency, with the steps that make it up: query embedding, search (vector and full-text together), rerank. The measured split (2026-11-10, [ADR 0009](../adr/0009-reranker-local-tei-service.md)) is that the Ollama embedding call is most of the non-rerank time, so it must be visible apart from the rest.
- A count of reranker fallbacks, split by cause (timeout or error), so "the reranker is always down" is one query.
- No new service to run for local development; one small dependency at most; no change in answers; negligible overhead (a few microseconds per observation, estimated, not measured).
- Fits where this is going: a stateless API that scales out and is scraped.

## Options in depth

**1. `prometheus-client` with a pull `/metrics` endpoint (chosen).** The library keeps counters and histograms in process memory and renders the text format. Pros: one pure-Python dependency, the de-facto standard, readable with `curl`, works with a local Prometheus or Grafana Alloy and with Grafana Cloud's free tier later. Cons: pull needs the scraper to reach every instance, and with several worker processes per container each process has its own numbers (see "At 1000x").

**2. OpenTelemetry SDK, OTLP push.** The vendor-neutral standard for metrics, traces and logs together; `PLAN.md` names it as the eventual target. Pros: traces come with it, and nothing scrapes the API. Cons: several packages (API, SDK, exporter, instrumentation), a collector to receive the data even locally, and more concepts before the first number shows. Metrics and the reranker counter do not need traces. Switching later costs little: an OpenTelemetry Collector reads Prometheus endpoints, and the observer seam below is the only place that names a metrics library.

**3. Hand-written counters served as JSON.** No dependency. But it invents a format no tool reads, and re-implements bucketing and thread-safety badly. It teaches less, since the project's aim includes using the industry's usual tool.

**4. Per-answer flag in the SSE stream** (also listed in #187). It shows a user or test that one answer fell back, but it says nothing about rates over time and changes the API contract ([ADR 0007](../adr/0007-api-web-contract.md)). A metric answers the operator's question; the flag would answer a different one and is left out.

**Where the code goes.** The retrieval code lives in `packages/rag`, which must not depend on a metrics library. `HybridRetriever` takes an optional observer (a small `Protocol` with two methods: a stage finished in N seconds, a rerank fell back for a reason). The API implements it with Prometheus objects. The package's tests use a recording fake, and without an observer the retriever behaves as before. This is the same shape as the model providers in [ADR 0003](../adr/0003-model-provider-interfaces.md).

**Labels.** Route labels use the route template (`/books/{book_id}/chat`), taken after routing, never the raw path; unmatched paths share one label (`unmatched`). Stage is one of `embed`, `search`, `rerank`; fallback reason is `timeout` or `error`. Every label has a fixed small set of values, so cardinality is bounded by code, not by traffic.

**What the request timer means for a stream.** For `/books/{id}/chat` the response is a stream. The middleware stops its clock when the last byte is sent, so the histogram records the full answer time, which is the number the serving benchmark ([#190](https://github.com/phuchaitt3/book-rag-app/issues/190)) reports too. Time to first byte is a different number, and is left to that benchmark.

**Security.** `/metrics` shows traffic shape and nothing about content. It has no authentication, like `/healthz`. In production it must be reachable by the scraper only (internal network or the platform's metrics path); this is a deployment item, not code.

## Measurements

None yet. The overhead claim is an estimate; the first check is the existing serving benchmark run with and without the middleware, once #190 lands.

## At 1000x the load

1. **Several processes per instance.** `prometheus-client` keeps numbers per process. One uvicorn process serves today. With several workers, a scrape would return one worker's numbers at random. Its multiprocess mode (a shared directory of files) fixes this; the alternative is one process per container, which the autoscaling design assumes anyway.
2. **Many instances.** The scraper reads each instance; counters add up across them and histograms with the same buckets merge, which is why the buckets are fixed in code, not chosen per instance.
3. **Cardinality** stays flat because labels are bounded. The thing that would break it is a label taken from user input; the unmatched-route label is there for that reason.
4. **Retention and cost** move to the monitoring backend: raw per-second data for weeks is expensive, so recording rules (precomputed p95) and downsampling come next.
5. **Tracing** becomes the question once a single slow answer must be explained, not an average. That is when OpenTelemetry traces earn their cost.

## Read more

- Prometheus docs, "Instrumentation" best practices and "Histograms and summaries" (bucket choice, why percentiles are computed server-side).
- Tom Wilkie, "The RED Method" (Grafana blog): the three numbers per service.
- Brian Brazil, *Prometheus: Up & Running*, chapter on instrumentation and cardinality.
- `prometheus_client` docs, "Multiprocess mode (Gunicorn)".
