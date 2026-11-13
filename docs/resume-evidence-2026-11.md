# Evidence report, 2026-11

Per task: what was built, the commit on `main`, how to reproduce it, and what was measured, under which conditions. Written for readers who check claims about this project against the repository.

**Rule:** a claim counts only if it runs at a commit on `main`, and a figure counts only with its script, its raw output in the repository and the conditions of its run. Small and negative results are reported too.

| Task | Commit on `main` | Evidence |
|---|---|---|
| 1. Real-model end-to-end run (#189) | `74ec919` (PR #196) | [benchmarks/e2e-real-model.md](benchmarks/e2e-real-model.md) |
| 2. Reranker in the API (#184) | `df0fb2e` (PR #188); measured in the app's path in PR #196 | [ADR 0009](adr/0009-reranker-local-tei-service.md), [benchmarks/book-retrieval.md](benchmarks/book-retrieval.md) |
| 3. Serving latency (#190) | `e7a4a4c` (PR #197) | [benchmarks/serving-latency.md](benchmarks/serving-latency.md) |

Common conditions, unless a section says otherwise: one Windows 11 laptop with an NVIDIA GTX 1660 Ti (6 GB) and 16 GB of RAM, Ollama 0.40.13, the Docker Compose stack of this repository, run on 2026-11-13. The book is Trần Trọng Kim, *Việt Nam sử lược*, Quyển I (public domain), and the questions come from the checked book test set ([experiments/book-testset/](../experiments/book-testset/README.md)). All runs are local; nothing here measures a deployed system.

## 1. Real-model end-to-end run (#189)

**Built.** Until this task, ingestion had only been tested with a fake embedder. A 338-page PDF of the book (Wikisource's export) was uploaded through the API and ingested by the worker with the real embedder, `bge-m3` through Ollama, and questions were asked through the chat endpoint. No code change was needed to ingest it. Added: a fetch script for the PDF, and a check that scores the app's own retrieval through the chat endpoint.

**Figures.** Ingestion: 392 chunks, all embedded, in 202 s. On the 208 blind questions, scored by whether a cited chunk holds the question's evidence sentence (top 6 cited chunks; bootstrap 95% CI):

| Arm | Hit@1 | Hit@5 | Median retrieval time |
|---|---|---|---|
| Reranker off | 47.6% (40.9–54.3) | 75.5% (69.7–81.2) | 0.14 s |
| Reranker on | 80.8% (75.5–86.1) | 88.9% (84.6–93.3) | 2.87 s |

**Negative result, reported as such.** Without the reranker, the app scores well below the in-memory benchmark on the same questions (75.5% against 89.4% Hit@5). A follow-up (#199, PR #205) changed the text, the search and the scoring one at a time: the cause is the app's full-text leg (Postgres `ts_rank_cd` over an OR query, no document-frequency weighting). With BM25 in its place the app reaches 86.5% on the PDF (+11.1 points, paired 95% CI 5.8–16.3); the PDF text, the scoring and the embedding side account for little or nothing ([benchmarks/retrieval-gap.md](benchmarks/retrieval-gap.md)). The fix is not built yet (#204).

**Reproduce.** `uv run python experiments/e2e/fetch_pdf.py`, `pnpm stack:up:rerank`, upload the PDF, then `BOOK_ID=<id> LABEL=rerank uv run python experiments/e2e/retrieval_check.py` (details and the reranker-off arm in the note). Raw results: `experiments/e2e/results/`.

## 2. Reranker in the API (#184)

**Built.** A cross-encoder rerank step in the API's hybrid retrieval: `BAAI/bge-reranker-v2-m3` served by Hugging Face TEI in Compose (`compose.reranker.yaml`, GPU, fp32), applied to the top 20 fused results, with a timeout and a fall-back to the fused order. Local runs only; production hosting is not decided ([ADR 0009](adr/0009-reranker-local-tei-service.md), #187).

**Figures.**

- Through the running app (task 1, on the PDF): Hit@1 from 47.6% to **80.8%** and Hit@5 from 75.5% to **88.9%**, for about 2.7 s more retrieval time per question. No question fell back to the fused order.
- Benchmark on the proofread HTML chunks (arm 5 of [book-retrieval.md](benchmarks/book-retrieval.md), 208 questions per set, in-memory, same GPU, fp32):

| Set | Hit@1 | Hit@5 |
|---|---|---|
| seen | 92.8 (89.4–96.2) | 99.0 (97.6–100) |
| blind | 85.1 (80.3–89.9) | 95.2 (92.3–98.1) |

Gain over arm 4 (bge-m3 + BM25, RRF k=60): +22.1 (16.8–27.4) Hit@1 on the seen set and +21.2 (15.4–26.9) on the blind set. The UIT-ViQuAD 2.0 figures are in [viquad-retrieval.md](benchmarks/viquad-retrieval.md) and were not rerun for this report.

**Reproduce.** `pnpm stack:up:rerank`; the benchmark steps are in [experiments/book-testset/README.md](../experiments/book-testset/README.md).

## 3. Serving latency (#190)

**Built.** A sequential client, [experiments/serving/measure.py](../experiments/serving/measure.py), that streams the chat endpoint and times the `citations` event, the first token and the end of the answer, over a fixed list of 30 questions (plus 3 warm-up), and writes raw records and a summary with the machine and model conditions.

**Figures.** Answer model `qwen2.5:3b-instruct` (Q4_K_M), embedder `bge-m3`, both kept loaded in Ollama; API built from `main` at `c3a41cf`; seconds, median / p90, 30 questions per arm, no errors:

| Arm | Citations | First token | Whole answer |
|---|---|---|---|
| Reranker off | 0.13 / 0.16 | 7.98 / 8.93 | 8.57 / 9.83 |
| Reranker on | 2.80 / 2.97 | 10.69 / 11.88 | 11.57 / 13.18 |

Cold start (first call after Ollama starts): 22 s for the 3B model, 21 s for `bge-m3`, 127 s for the 7B model. The app's default answer model, `qwen2.5:7b-instruct`, does not stay loaded next to the reranker and the embedder on a 6 GB GPU, so it was not measured. These are latency figures only: no answer was scored, and no evaluation of answer quality exists yet.

**Reproduce.** See "Reproduce" in [serving-latency.md](benchmarks/serving-latency.md). Raw results: `experiments/serving/results/`.

## What these figures do not show

- Behaviour under concurrent users (no load test was run).
- Any hosted or production setup (production would use hosted models, ADR 0003).
- Answer quality, for any model.
- Any book other than this one.
