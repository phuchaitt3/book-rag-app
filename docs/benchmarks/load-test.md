# Load test: API with fake providers (#227)

**Status:** thresholds and ramp fixed before any run (section 2). Results are added below them; nothing above "Results" changes after a run.

## 1. Question and expected knee

Where does the API bend first when virtual users are added, on one machine, with the paid models faked? Expected first bottleneck (a guess, to be checked): the single uvicorn process (one event loop, one CPU) or the SQLAlchemy pool (default 5 + 10 overflow = 15 connections) for chat; the worker (Procrastinate runs one job at a time by default) for ingestion.

## 2. Fixed before the first run

**Why k6.** It runs from the `grafana/k6` image (no new dependency), has per-request timings, thresholds and a JSON summary. Its `http` module buffers a response, so it cannot read the first SSE event as it arrives. Chat is therefore judged by (a) `http_req_waiting` (time to the response headers; the API sends them when retrieval has finished and the stream starts, so this is retrieval plus queueing), (b) total duration, and (c) a check that the body ends with an `event: done`. Locust would not change this (it also buffers by default) and needs a Python dependency.

**Conditions (assumptions, not measurements).** Fake LLM: first token after 0.8 s, then 0.03 s per word, fixed 60-word reply (nominal stream 2.57 s). Fake question embedder: 0.05 s per call. Fake ingestion embedder: 0.3 s per batch of 32. No injected errors (this measures the API's own limits). The real figures come from a paid calibration run that #155 has not done; these are placeholders and the doc says so next to every number. Chat rate limit is switched off (`CHAT_RATE_LIMIT=0`), because the default 30 per minute per address would turn a test from one address into 429s; its effect is not tested. Containers: api 1 CPU / 768 MB, worker 1 CPU / 768 MB, db 2 CPU / 1 GB, one uvicorn process (the Dockerfile's command). Data is synthetic: generated Vietnamese-like PDFs, hashed fake embeddings.

**SLOs** (a step fails when any holds over its 60 s hold window):

| Scenario | Metric | Threshold |
|---|---|---|
| Chat | time to response start (`http_req_waiting`) p95 | <= 1.0 s |
| Chat | total duration p95 | <= 6.0 s (nominal 2.6 s + 3.4 s) |
| Chat | error rate (non-200, or no `event: done`) | <= 1% |
| Book list and read | duration p95 | <= 0.3 s |
| Book list and read | error rate | <= 1% |
| Upload | POST duration p95 | <= 3.0 s |
| Ingestion | upload to `succeeded` p95 | <= 90 s |
| Ingestion | failed jobs | 0 |

**Ramp, chat plus reads together.** Steps of virtual users: 5, 10, 20, 40, 80, 160, 320. At each step N chat users (ask, wait 10 s, ask again) and N reader users (list books, get one, wait 3 s) run together; 15 s ramp then 60 s hold, the 15 s ramp excluded from the numbers. A warm-up run at 5 users is discarded. Stop one step after the first step that breaks an SLO, or earlier if any container passes 90% of its memory limit. The saturation point is the highest step that passes; the break step is the next.

**Ramp, upload and ingestion.** Uploads of one 10-page synthetic PDF at a constant arrival rate of 0.1, 0.25, 0.5, 1, 2 per second, 60 s each, then wait up to 180 s for the queue to drain. Same stop rule.

**Recorded per step:** requests per second, p50/p95/p99, error rate, database pool wait (time inside `pool.connect`) and pool use, event-loop lag, and CPU and memory per container (`docker stats`, every 5 s).

**Not tested:** real model latency or quality, provider errors (429, 5xx, timeouts), the chat rate limit, more than one API process or machine, a managed database, real PDFs, a real network, long runs (each step is 60 s, so p99 rests on few samples at low steps).
