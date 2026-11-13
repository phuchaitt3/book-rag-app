# Serving latency: time to first token and total answer time

Issue #190. **Status: not yet run.** Every figure below reads `TBD (not yet run)` until the run is made at a commit on `main` and the numbers are copied from its `-summary.json`. Script and questions: [experiments/serving/](../../experiments/serving/measure.py).

## Purpose

How long one user waits for an answer about one book through the app's own chat endpoint (`POST /books/{BOOK_ID}/chat`, streamed over SSE): the time until the first streamed token, and the time until the whole answer is done. It is run with the reranker off and on, so the cost of the reranker (ADR 0009) is visible in the user's wait and not only in the retrieval step. It is not a load test: one request at a time, one user.

## Conditions

| Item | Value |
|---|---|
| Machine GPU / VRAM | TBD (not yet run) |
| Ollama version | TBD (not yet run) |
| Chat model | `qwen2.5:7b-instruct` (default `llm_model` in `apps/api/src/book_rag_api/config.py`) |
| Chat model quantisation | TBD (not yet run) |
| Embedding model | `bge-m3` (default `embedding_model` in `config.py`) |
| TEI image (reranker arm) | `ghcr.io/huggingface/text-embeddings-inference:turing-1.9.4` (`compose.reranker.yaml`) |
| Commit | TBD (not yet run) |
| Date | TBD (not yet run) |
| Book | TBD (not yet run) |

The script records GPU, Ollama version, model digest and quantisation, TEI image, commit and date in the `conditions` block of each summary file, so the table is filled from there and not from memory.

## Method

[experiments/serving/measure.py](../../experiments/serving/measure.py) sends each question to `POST {API_URL}/books/{BOOK_ID}/chat` with `top_k` 6, one request at a time (sequential, no concurrency), and reads the SSE stream. It records seconds from just before the request is sent (`time.perf_counter`) to each of three events:

- **t_citations:** the first `citations` event. Retrieval, and reranking when on, are done by then.
- **t_first_token:** the first `token` event.
- **t_total:** the `done` event.

An event counts when its `event:` line arrives, which is when the server flushed it. A request that raises, streams an `error` event, or never reaches `done` is counted as an error and left out of every timing.

The question file is [experiments/serving/questions.json](../../experiments/serving/questions.json): 33 blind-form questions picked with `random.Random(2026)` by `make_questions.py`. The first 3 are warm-up (run, not counted, so model load and caches do not enter the figures); the other **30 are counted**.

Median and p90 use the nearest-rank method: for n sorted values, the value at 1-based rank `ceil(p/100 * n)`. The median is the 50th percentile by the same rule (the lower middle value for even n). Raw per-question records go to `OUT_DIR/<LABEL>.jsonl`, and the summary to `OUT_DIR/<LABEL>-summary.json`.

## Results

Seconds. n is the number of counted questions; errors are counted separately and excluded from the timings.

**Reranker off** (`pnpm stack:up`)

| Timing | n | median | p90 | errors |
|---|---|---|---|---|
| t_citations | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |
| t_first_token | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |
| t_total | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |

**Reranker on** (`pnpm stack:up:rerank`)

| Timing | n | median | p90 | errors |
|---|---|---|---|---|
| t_citations | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |
| t_first_token | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |
| t_total | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) | TBD (not yet run) |

## Reproduce

Start the stack for the arm, ingest the book, then run the script under the machine-wide GPU lock. Run the off arm first, then bring the stack down and run the on arm.

```sh
pnpm stack:up            # reranker off
# or
pnpm stack:up:rerank     # reranker on (TEI service)

BOOK_ID=<id of the ingested book> LABEL=rerank-off API_URL=http://localhost:8000 \
  python ~/claude-config/scripts/gpu_run.py run --wait -- \
  uv run python experiments/serving/measure.py
```

Use `LABEL=rerank-on` for the second arm. `WARMUP`, `QUESTIONS`, `OUT_DIR`, `OLLAMA_URL`, `LLM_MODEL` and `EMBEDDING_MODEL` are optional and documented at the top of `measure.py`. `pnpm stack:down` stops either stack.

## Limits

- **Small sample:** 30 counted questions per arm, so p90 rests on very few values and the figures are noisy. No confidence interval is computed.
- **One laptop, one GPU:** the figures say nothing about other hardware, and the GPU is shared by chat, embedding and the reranker.
- **Local only:** Ollama and TEI run in the local compose stack, not on a deployed system.
- **Not production:** one user, one request at a time, one book; it shows no behaviour under concurrent load.
