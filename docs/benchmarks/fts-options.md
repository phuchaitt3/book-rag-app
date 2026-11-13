# Options for the app's full-text search leg (#204)

[#199](retrieval-gap.md) found that the app's full-text leg (`ts_rank_cd` over an OR `to_tsquery`) is why its retrieval is below the benchmark. This note measures ways to fix it, one at a time, on the same 208 blind questions, corpora, scoring and RRF as #199 ([fts_options.py](../../experiments/e2e/fts_options.py); numbers in [fts-options-204.json](../../experiments/e2e/results/fts-options-204.json)). Only the lexical leg changes; the dense leg is the app's own (pgvector over Ollama bge-m3).

**Result.** BM25 computed inside Postgres from the existing `tsvector` gives the same retrieval as the benchmark's in-memory BM25: fused Hit@5 **86.5%** on the PDF (today 75.5%) and **89.4%** on the HTML chunks (today 76.9%), with identical 95% intervals. It needs no new table and no extension. It costs more time per query than today's leg: about 80 ms against 14 ms (median, 392 chunks, local, warm). Dropping common words or changing `ts_rank_cd`'s length normalisation does not close the gap.

## Hit@5 and Hit@1 (percent, 208 questions; fused = RRF k=60, 30 candidates per leg)

| Lexical leg fused with the app's dense leg | PDF Hit@5 | PDF Hit@1 | HTML Hit@5 | HTML Hit@1 |
|---|---|---|---|---|
| none (dense alone) | 79.3 | 52.4 | 85.6 | 60.1 |
| `ts_rank_cd` (the app today) | 75.5 | 47.6 | 76.9 | 46.2 |
| `ts_rank_cd` with length normalisation 1 | 75.0 | 46.6 | 77.9 | 47.6 |
| `ts_rank_cd` with length normalisation 2 | 73.6 | 45.2 | 77.9 | 48.1 |
| `ts_rank_cd`, words in over 50% of chunks dropped | 80.3 | 50.5 | 82.2 | 51.9 |
| `ts_rank_cd`, words in over 20% dropped | 82.2 | 51.9 | 82.7 | 53.8 |
| `ts_rank_cd`, words in over 10% dropped | 85.6 | 51.4 | 86.5 | 53.8 |
| `ts_rank_cd`, words in over 5% dropped | 81.2 | 54.8 | 85.6 | 59.1 |
| **BM25 in Postgres** (stats per query) | **86.5** | **64.9** | **89.4** | **63.5** |
| BM25 in Postgres, words in over 50% of chunks dropped | 86.5 | 63.5 | 89.4 | 62.0 |
| BM25 in memory (the benchmark's) | 86.5 | 63.0 | 89.4 | 63.5 |

Alone, the lexical leg's Hit@5 is 58.2 (PDF) for `ts_rank_cd` and 84.1 for either BM25. The word-dropping rows are not monotonic in the cut-off (best at 10% on both books) and each stays 0.9 to 6.2 points under BM25 on the PDF in Hit@5 and about 8 to 14 points under it in Hit@1, with overlapping Hit@5 intervals at this sample size; read them as "helps some, unstable", not as a tuned setting. The two BM25 implementations agree on the top 5 in the same order for only 73 of 208 questions (ties and tokenisation differ: `simple` text search against `\w+`), but not on whether the evidence chunk is found. The full per-leg intervals are in the JSON.

## What BM25 in Postgres costs

The query ([fts_options.py](../../experiments/e2e/fts_options.py), `BM25_SQL`) unnests the book's `tsvector`s to get term frequencies, chunk lengths and document frequencies, then scores with k1 1.2, b 0.75. Per question, 208 questions, one connection, warm:

| Leg | Median | p95 |
|---|---|---|
| `ts_rank_cd` (today), PDF / HTML | 14.1 / 13.1 ms | 25.4 / 24.6 ms |
| BM25 in Postgres, PDF / HTML | 84 / 76 ms | 97 / 88 ms |
| same, common words dropped, PDF / HTML | 77 / 62 ms | 110 / 72 ms |
| same with the statistics stored in tables (not per query), PDF | 69 ms | 106 ms |

Storing the document frequencies and chunk lengths in tables ([fts_stats_latency.py](../../experiments/e2e/fts_stats_latency.py), which creates and drops its own tables) saves only about 15%, so the cost is not recomputing statistics: it is unnesting and scoring every chunk that matches any query word, and an OR of a natural-language question matches nearly every chunk. This grows with the book's chunk count, which is the scalability concern: today's leg shares that growth but at a fifth of the constant.

## Options, weighed against the goals

| Option | Measured quality | Cost and scale | Verdict |
|---|---|---|---|
| BM25 in Postgres from the `tsvector` | matches in-memory BM25 | +65 ms per query at 392 chunks; linear in chunks that match any query word; no schema change | works now; needs a bound on the candidate set before it suits large books |
| BM25 in the application (candidate rows from Postgres, scored with per-book statistics) | not measured here; same formula, so same quality | moves the work to Python; needs the statistics cached per book and invalidated on ingest | not measured: the in-Postgres result is the quality ceiling, and the latency comparison is the open question |
| Drop common query words | +4.8 to +10.1 points on the PDF, unstable | free | a cheap stopgap, not a fix |
| `ts_rank_cd` normalisation flags | none (−0.5 to −1.9 on the PDF) | free | ruled out |
| A Postgres BM25 extension | not measured | the Compose image (pgvector) has none; a new image or a managed Postgres that ships one | not measured; belongs in the ADR 0002 research ([#90](https://github.com/phuchaitt3/book-rag-app/issues/90)) |

## Bounding the cost (#208)

[fts_bounded.py](../../experiments/e2e/fts_bounded.py) stores the statistics and takes as candidates only the chunks the GIN index finds for the query's rare words (in at most SHARE of the chunks), then scores them with BM25 over every query word ([fts-bounded-208.json](../../experiments/e2e/results/fts-bounded-208.json)). Median per question, PDF, with fused Hit@5 on PDF / HTML:

| SHARE | Median | p95 | Fused Hit@5 | Leg alone Hit@5 (PDF) |
|---|---|---|---|---|
| 1.0 (no bound) | 26 ms | 46 ms | 86.5 / 89.4 | 84.1 |
| 0.5 | 26 ms | 46 ms | 86.5 / 89.4 | 84.1 |
| **0.2** | **11 ms** | 19 ms | **86.5 / 88.9** | 83.7 |
| 0.1 | 5 ms | 9 ms | 85.6 / 88.0 | 76.4 |
| 0.05 | 2 ms | 5 ms | 83.7 / 86.5 | 62.0 |

At 0.2 the leg is faster than today's `ts_rank_cd` (14 ms) with the BM25 quality; below it the leg's recall falls. This changes the verdict above: the 80 ms was the per-query statistics and the unbounded candidate set, not BM25. The design is proposed in [ADR 0011](../adr/0011-bm25-in-postgres-stored-statistics.md).

## What follows

- Adopting any of these changes the search design, so it needs an ADR, and the choice is a latency-against-quality trade that is the user's to weigh: BM25 in Postgres restores the 11 points but multiplies the leg's time by about 5 on this book. Follow-up issue: bound the candidate set (for example, take the GIN matches on only the query's rarest words) and re-time.
- The reranker (ADR 0009) still hides the gap when it works; the fix matters when it is off or fails, and for Hit@1 before reranking.
- The end-to-end re-measurement with the reranker off and on, listed in #204, waits for the chosen design.

## Limits

One book (two chunkings of it), 208 synthetic questions, one run; latency from one local machine, Postgres in Docker, 392 chunks, so the growth rate with book size is argued, not measured. The intervals are bootstrap over questions. Reproduce as in [retrieval-gap.md](retrieval-gap.md), with `fts_options.py` in place of `gap.py`.
