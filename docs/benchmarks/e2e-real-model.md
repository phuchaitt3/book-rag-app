# Real-model end-to-end run: a Vietnamese book PDF through the running app (#189)

Until this run, ingestion had only been tested with a fake embedder. This note records one real run on the Compose stack: a PDF uploaded through the API, ingested by the worker with bge-m3 through Ollama, then questioned through the chat endpoint, with the reranker off and on.

**Result.** The PDF ingested (338 pages, 392 chunks, all embedded, 202 s) and a question answered with a streamed reply citing section and page. On the 208 blind questions of the [book test set](../../experiments/book-testset/README.md), the app's own retrieval finds the evidence sentence in the top 5 cited chunks for **75.5%** of questions without the reranker and **88.9%** with it. Hit@1 goes from **47.6% to 80.8%**. The reranker adds about 2.7 s to the median retrieval time (0.14 s to 2.87 s).

The no-reranker figure is well below the in-memory benchmark on the same questions ([book-retrieval.md](book-retrieval.md), arm 4: 89.4% Hit@5). This run does not say why; [retrieval-gap.md](retrieval-gap.md) (#199) does: the app's full-text leg.

## Conditions

| Item | Value |
|---|---|
| Book | Trần Trọng Kim, *Việt Nam sử lược*, Quyển I, Wikisource PDF export (public domain in Vietnam), fetched by [fetch_pdf.py](../../experiments/e2e/fetch_pdf.py) |
| PDF | 338 pages, 6,333,184 bytes, SHA-256 `401a2ac6d3a93a2bca6a6901c2149a1733fa8a77d12c45c1f682ccb067d301aa` (the export is generated, so its bytes can change) |
| Parsed and chunked | 35 sections, 392 chunks (the test set's HTML version of the book: 359 chunks) |
| Machine | Windows 11 laptop, NVIDIA GTX 1660 Ti, 6 GB VRAM, driver 616.92, 16 GB RAM |
| Embedder | `bge-m3` through Ollama 0.40.13 (the worker and the API) |
| Reranker (arm "on") | `BAAI/bge-reranker-v2-m3`, Hugging Face TEI `turing-1.9.4`, fp32, depth 20, `compose.reranker.yaml` |
| Answer model | `qwen2.5:7b-instruct` (used only for the smoke question; the retrieval check stops the stream after the `citations` event, and the API ran with the fake LLM) |
| Code | commit `df0fb2e` (`main` before #191 and #193); the scripts are in this branch |
| Questions | the 208 `blind` questions of `experiments/book-testset/questions.jsonl` (checked set), all scored |
| Date | 2026-11-13 |

## What was measured

[retrieval_check.py](../../experiments/e2e/retrieval_check.py) posts each question to `POST /books/{id}/chat` with `top_k` 6, reads the `citations` event (the ranked chunks the answer would cite), and closes the stream. A hit at rank k means one of the first k cited chunks contains the question's `evidence` sentence. The test set's gold chunk numbers belong to the HTML chunking, so they are not used. Text is compared as lowercase letters only (no spaces, punctuation, digits or Han characters), because the PDF puts page numbers and footnote marks inside sentences and adds the Han spelling after names. Intervals are bootstrap 95% (10,000 resamples, seed 189). A smoke run of 10 questions skipped 3 for those reasons before the matching was loosened; the full run skipped none.

| Arm | Hit@1 | Hit@5 | Median retrieval time | Misses in top 6 |
|---|---|---|---|---|
| Reranker off | 47.6% (40.9–54.3) | 75.5% (69.7–81.2) | 0.136 s | 48 |
| Reranker on | **80.8%** (75.5–86.1) | **88.9%** (84.6–93.3) | 2.865 s | 22 |

Raw per-question ranks: [retrieval-no-rerank.json](../../experiments/e2e/results/retrieval-no-rerank.json) and [retrieval-rerank.json](../../experiments/e2e/results/retrieval-rerank.json). The API log of the reranker run holds no reranker failure or timeout warning, so no question fell back to the fused order.

## What the run showed

- **Ingestion with the real embedder works.** The upload, parsing, chunking and embedding of a real 338-page PDF ran without a code change. The job reached `succeeded` in 202 s on this GPU.
- **A real answer streams with citations.** One question ("Nước Việt ta khởi đầu có sử từ đời nào, vào thế kỷ thứ mấy?") returned "Đời nhà Trần, vào quãng thế kỷ thứ XIII [1]" with six citations (sections and printed pages). Its first token took 133 s because the 7B model was loading with about 1.9 GB of free RAM. That is a cold start and is not a serving figure; the serving note measures warm answers.
- **The reranker is the largest effect in the app too:** +33.2 points Hit@1 and +13.4 points Hit@5 against no reranker, the same direction and order of size as the benchmark's arm 5 (+22 Hit@1 over fusion).

## Open question, answered in #199: why is the app below the benchmark?

The same 208 questions reach 89.4% Hit@5 in the in-memory benchmark (arm 4) and 75.5% here. [retrieval-gap.md](retrieval-gap.md) changes the text, the search and the scoring one at a time: the cause is the app's full-text leg (`ts_rank_cd` over an OR query, no document-frequency weighting). With the benchmark's BM25 in its place the app's fused Hit@5 is 86.5% on this PDF. The PDF's text costs 1 to 3 points (not significant), and the scoring and the embedding side cost nothing.

## Reproduce

```sh
uv run python experiments/e2e/fetch_pdf.py          # writes experiments/e2e/data/vsl.pdf (git-ignored)
pnpm stack:up:rerank                                 # Compose: Postgres, S3, migrate, API, worker, TEI reranker
# upload the PDF (any client that sends a multipart "file"), wait for the ingestion job to succeed
BOOK_ID=<uuid> LABEL=rerank uv run python experiments/e2e/retrieval_check.py
# for the other arm, set the API's reranker provider to none, recreate the api container, and use the label no-rerank
```

Set `CHAT_RATE_LIMIT=0` on the API for the check: it sends 208 questions in a few minutes, and since #193 the default limit is 30 per minute per client. (The reranker-off run above was made before that limit existed.)

## Limits

One book, one machine, one run per arm, no repeats. The questions were written from the HTML chunks of the same book, so the PDF's text and chunk boundaries are new to them. The answer quality was checked on one question only; no figure here measures the generated answers.
