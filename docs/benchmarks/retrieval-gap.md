# Why the app's retrieval is below the benchmark: the full-text leg (#199)

On the same 208 blind questions, the in-memory benchmark reaches 89.4% Hit@5 ([book-retrieval.md](book-retrieval.md), arm 4) and the running app on the PDF reaches 75.5% ([e2e-real-model.md](e2e-real-model.md), reranker off). The two runs differed in the text, the search and the scoring. This note changes one at a time.

**Result.** The gap is the app's full-text search. Swapping only that leg for the benchmark's BM25 lifts the app's fused Hit@5 from 75.5% to 86.5% on the PDF (+11.1 points, 95% CI 5.8–16.3) and from 76.9% to 89.4% on the HTML chunks (+12.5, 7.7–17.3). The text (PDF against HTML chunks) costs 1.4 to 2.9 points, with intervals that include zero. The scoring costs nothing. The embedding side costs nothing: pgvector over Ollama's bge-m3 and the benchmark's in-memory bge-m3 give the same fused result. In the app, fusion makes things worse than the dense leg alone (75.5% against 79.3% on the PDF; the difference's interval reaches zero), because the full-text leg ranks badly.

## Method

[gap.py](../../experiments/e2e/gap.py) scores every arm on the 208 blind questions, with one scoring rule: a hit at rank k means one of the first k chunks contains the question's evidence sentence (letters only, as in [retrieval_check.py](../../experiments/e2e/retrieval_check.py)). Two corpora, each in Postgres:

- **P:** the PDF's 392 chunks, as the worker ingested and embedded them (#189).
- **H:** the proofread HTML's 359 chunks, loaded into the same database as a second book, embedded with the same Ollama model.

Four search legs, 30 candidates each, fused by RRF (k=60) as the app does:

| Leg | What it is |
|---|---|
| dense_app | pgvector cosine over Ollama bge-m3 vectors (the app's SQL, iterative scan on) |
| fts_app | `to_tsvector('simple')`, an OR `to_tsquery` of every query word, ordered by `ts_rank_cd` (the app's SQL) |
| dense_st | sentence-transformers bge-m3, in-memory cosine (the benchmark's) |
| bm25 | the benchmark's BM25 (k1 1.2, b 0.75) |

Two checks that the harness measures the same things as the earlier runs: the app's fused arm on the PDF gives **75.5%** Hit@5 and 47.6% Hit@1, the figures the live API gave in #189; the benchmark's fused arm on the HTML chunks gives **89.4%**, the figure in [book-retrieval.md](book-retrieval.md). On H, scoring by the test set's gold chunk numbers and by the evidence sentence gives the same sets for all 208 questions, so the scoring factor is zero by construction here.

## Results

Hit@5 in percent on all 208 questions (95% bootstrap CI for the fused arms; the per-leg intervals are in [gap-199.json](../../experiments/e2e/results/gap-199.json)).

| Arm | PDF chunks (P) | HTML chunks (H) |
|---|---|---|
| dense_app | 79.3 | 85.6 |
| dense_st | 79.3 | 84.6 |
| fts_app | 58.2 | 57.2 |
| bm25 | 84.1 | 86.1 |
| **Fused, app legs** (dense_app + fts_app) | **75.5** (69.7–81.2) | 76.9 (71.2–82.7) |
| Fused, benchmark legs (dense_st + bm25) | 86.5 (81.7–90.9) | **89.4** (85.1–93.3) |
| Fused, dense_app + bm25 | 86.5 | 89.4 |
| Fused, dense_st + fts_app | 75.5 | 77.4 |

**One factor at a time** (paired Hit@5 differences, 95% bootstrap):

| Factor changed | Between | Change | CI |
|---|---|---|---|
| Scoring (gold chunk numbers to evidence sentence) | benchmark arm 4 on H | 0.0 | the two scorings agree on every question |
| Dense leg (Ollama + pgvector to sentence-transformers) | benchmark's BM25 fusion on P | 0.0 | 0.0 to 0.0 |
| **Lexical leg** (`fts_app` to BM25) | on P | **+11.1** | 5.8 to 16.3 |
| **Lexical leg** | on H | **+12.5** | 7.7 to 17.3 |
| Text (HTML chunks to PDF chunks) | benchmark legs | −2.9 | −6.7 to 0.5 |
| Text (HTML chunks to PDF chunks) | app legs | −1.4 | −6.2 to 2.9 |

The whole gap (89.4 to 75.5, 13.9 points) is the text step (−2.9) plus the lexical-leg step (−11.1), going H to P and benchmark legs to app legs; the other order gives −12.5 and −1.4. The lexical leg is significant in both orders; the text is not.

## Why the full-text leg is weak

The app's leg ORs every word of the question and ranks with `ts_rank_cd`, which does not weight rare words more than common ones. Common words of a question probably match nearly every chunk, so a chunk that repeats them can outrank the one holding the rare name (the probe below is the evidence; no individual question was traced). Alone it finds the evidence in the top 5 for 57–58% of questions, against 84–86% for BM25.

A probe supports this and shows it is not the whole story: with the question's words that occur in more than 20% of the chunks left out of the full-text query, the fused arm reaches 82.2% on P and 82.7% on H; at 5% it reaches 81.2% and 85.6%. That recovers between half and 70% of the gap to the benchmark's lexical leg (+6.7 and +5.7 points on P, +5.8 and +8.7 on H, of 11.1 and 12.5). The remainder is the ranking itself (no document-frequency weighting, no length normalisation). These two cut-offs are a diagnosis, not a tuned fix, and both are reported.

## What follows

- A fix belongs in the app's lexical leg, not in the text or the embedder. The options are to rank in the application (fetch candidate rows and score with BM25 over the book's token statistics), to filter common words from the query, or to use a Postgres BM25 extension; each changes the search design and needs its own measurement on this test set. They are follow-up work, not part of this note.
- The reranker hides most of this: with it the app reaches 88.9% Hit@5 on the PDF (#189). The gap matters when the reranker is off or fails and the fused order is returned (ADR 0009), and for Hit@1 before reranking.
- The accent-insensitive search (#95), whitespace in parsing (#152) and the RRF weight (#180) are separate issues; this run did not need any of them to explain the gap.

## Limits

One book, 208 synthetic questions, one run (the embeddings are deterministic; the intervals are bootstrap over questions). The PDF export's bytes can change, so P is the ingested copy. The probe's stop-word cut-offs were not tuned. Reproduce with Postgres from the #189 stack (book id in `BOOK_ID`), Ollama with bge-m3, and:

```sh
BOOK_ID=<uuid> uv run --with sentence-transformers --with scipy --with torch \
  --index https://download.pytorch.org/whl/cu128 python experiments/e2e/gap.py
```

`OLLAMA_URL` and `DATABASE_URL` override the defaults; embeddings are cached in `experiments/e2e/data/gap/` (git-ignored). The script adds a book titled "GAP-199 HTML chunks" to the database it runs against.
