# Serving latency: time to first token and total answer time (#190)

How long one user waits for an answer about one book through the app's own chat endpoint (`POST /books/{id}/chat`, streamed over SSE), with the reranker off and on. It is not a load test: one request at a time, one user, one laptop.

**Result.** With `qwen2.5:3b-instruct` as the answer model, the first streamed token arrives after a median of **8.0 s** without the reranker and **10.7 s** with it, and the whole answer after **8.6 s** and **11.6 s**. The reranker costs about 2.7 s per question, all of it before the citations are sent. Most of the remaining wait is the model reading the six cited passages before it writes: about 7.9 s between the citations and the first token in both arms. On this 6 GB GPU the app's default answer model (7B) does not stay loaded next to the reranker and the embedder, so it was not measured (see "The 7B default").

## Results

Seconds, 30 counted questions per arm, no errors in either arm. Nearest-rank median and p90.

| Arm | Citations (retrieval) median / p90 | First token median / p90 | Whole answer median / p90 |
|---|---|---|---|
| Reranker off | 0.13 / 0.16 | 7.98 / 8.93 | 8.57 / 9.83 |
| Reranker on | 2.80 / 2.97 | 10.69 / 11.88 | 11.57 / 13.18 |

Raw records and summaries, with the conditions the script captured: [experiments/serving/results/](../../experiments/serving/results/) (`qwen3b-rerank-off*`, `qwen3b-rerank-on*`).

## Conditions

| Item | Value |
|---|---|
| Machine | Windows 11 laptop, NVIDIA GTX 1660 Ti 6 GB (driver 616.92), 16 GB RAM, 1.6–3.2 GB of it free at the readings taken that evening |
| Answer model | `qwen2.5:3b-instruct`, Q4_K_M, 3.1B parameters, digest `357c53fb…`, context 4096, through Ollama 0.40.13 |
| Embedding model | `bge-m3`, F16, 567M parameters, digest `79076464…`, through the same Ollama |
| Ollama settings | `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_MAX_LOADED_MODELS=2`; both models were resident on the GPU for both arms |
| Reranker (arm "on") | `BAAI/bge-reranker-v2-m3`, TEI `turing-1.9.4`, fp32, depth 20 (`compose.reranker.yaml`) |
| API | built from `main` at `c3a41cf` (includes the chat timeouts and rate limit of #193 and `/metrics` of #195, at their defaults), `top_k` 6 |
| Book | *Việt Nam sử lược*, Quyển I, Wikisource PDF export, 338 pages, 392 chunks ([e2e-real-model.md](e2e-real-model.md)) |
| Questions | [questions.json](../../experiments/serving/questions.json): 33 blind questions of the book test set drawn with seed 2026; the first 3 are warm-up and not counted |
| Date | 2026-11-13 |

## Method

[measure.py](../../experiments/serving/measure.py) sends each question to the chat endpoint, one at a time, and reads the stream. It records seconds from just before the request is sent to three events:

- **Citations:** the `citations` event. Query embedding, both searches, fusion and (arm "on") reranking are done by then.
- **First token:** the first `token` event.
- **Whole answer:** the `done` event.

A request that raises, streams an `error` event or never reaches `done` counts as an error and is left out of the timings; there were none. Median and p90 use the nearest-rank method (the value at rank `ceil(p/100 × n)` of the sorted values). With 30 values, p90 is the 27th: a rough tail, not a stable one.

## Cold start

The first request after Ollama starts pays for loading the models. Measured with one call each through Ollama's API, before the runs: `qwen2.5:3b-instruct` 22 s, `bge-m3` 21 s, `qwen2.5:7b-instruct` 127 s. The warm-up questions absorb this, so it is not in the table. A user who asks the first question after a restart waits that long, and with Ollama's default keep-alive (5 minutes) again after every idle spell.

## The 7B default

The app's default answer model is `qwen2.5:7b-instruct`. On this GPU, with the reranker holding 2.2 GB, Ollama keeps only one model loaded: the 7B model (5.2 GB, 18% of it on the CPU) and `bge-m3` replace each other on every question. Ollama reported load times of about 47 s for the 7B model and 15 s for `bge-m3` on each switch. The serving run was not made with it: it would measure model loading, not the app, and it heats the laptop. Two things follow for a local setup on a 6 GB card: use the 3B model (set `LLM_MODEL`), or run without the reranker. Which answer model is good enough is a separate question: no evaluation of answer quality exists yet, so these figures say nothing about the answers (see #22, #168).

## Reproduce

```sh
# Ollama on the host with both models pulled; keep them loaded for the run:
#   OLLAMA_KEEP_ALIVE=30m OLLAMA_MAX_LOADED_MODELS=2 ollama serve
LLM_MODEL=qwen2.5:3b-instruct pnpm stack:up:rerank        # arm "on"
# ingest the book (see e2e-real-model.md), then, under the machine-wide GPU lock:
BOOK_ID=<id> LABEL=qwen3b-rerank-on LLM_MODEL=qwen2.5:3b-instruct \
  python ~/claude-config/scripts/gpu_run.py run --wait -- uv run python experiments/serving/measure.py
# arm "off": recreate the api with the reranker provider set to none, then LABEL=qwen3b-rerank-off
```

## Limits

- **Small sample:** 30 questions per arm, one run each, no repeats and no confidence interval.
- **One laptop:** a 6 GB consumer GPU shared by the answer model, the embedder and the reranker, with little free RAM. Other hardware will differ.
- **Local, not production:** production would call hosted models (ADR 0003), and this says nothing about them.
- **One user:** sequential requests; nothing here shows behaviour under concurrent load.
- **Latency only:** the answers were not scored.
