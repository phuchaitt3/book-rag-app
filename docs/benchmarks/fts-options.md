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

## Growth with book size (#208)

[fts_scale.py](../../experiments/e2e/fts_scale.py) times the shipped BM25 leg (bounded candidates, stored statistics, [ADR 0011](../adr/0011-bm25-in-postgres-stored-statistics.md)) and the `ts_rank_cd` search it replaced on synthetic books of growing chunk count ([fts-scale-208.json](../../experiments/e2e/results/fts-scale-208.json)). Median and p95 per query, 100 real test-set questions, two passes each, 30 candidates, Postgres in a 2 GB container:

| Chunks | BM25 bounded median / p95 | `ts_rank_cd` median / p95 |
|---|---|---|
| 392 | 84 / 484 ms | 19 / 36 ms |
| 3,920 | 136 / 335 ms | 153 / 287 ms |
| 11,760 | 355 / 987 ms | 500 / 1,058 ms |
| 39,200 | 1,285 / 3,389 ms | 1,594 / 3,075 ms |

From 3,920 to 39,200 chunks (10 times) the BM25 median grows 9.4 times and the `ts_rank_cd` median 10.4 times: both legs grow about linearly with chunk count here, and BM25 is 10 to 30% faster in the median from 3,920 chunks up. The p95 of BM25 is higher than `ts_rank_cd` at 392 and 39,200 chunks and lower at the two sizes between, so the data does not separate the tails.

What this shows for scaling: the bound does not change the growth rate on this data. A book of 39,200 chunks (about 100 times the real one) costs over a second per query on either leg, so a large book needs a different remedy (for example a smaller candidate share or a cap on candidates), not only the bound.

The data is synthetic: each chunk is a random draw of words from the real book's word frequencies, so common words are as common as in the real text and an OR query matches almost every chunk, but word order, co-occurrence and rare-word clustering are lost. It supports a latency claim only, never a quality claim. The smallest size (392 chunks, the real book's count) took 84 ms here against 11 ms on the real book above, so the synthetic text is a harsher case than the real one, probably because rare words are less concentrated and the bound removes fewer candidates; this was not checked. The 392-chunk row ran first, and its high p95 may include warm-up. One run, one machine, one 2 GB container, 100 queries.

## Accent-insensitive keyword search (#95)

[fts_unaccent.py](../../experiments/e2e/fts_unaccent.py) asks whether an `unaccent` step in the keyword leg changes what it finds ([fts-unaccent-95.json](../../experiments/e2e/results/fts-unaccent-95.json)). Arm A is today's `simple` configuration. Arm B indexes `to_tsvector('simple', unaccent(text))` in a second column and runs `unaccent` over the query too. The book's 359 chunks sit in a throwaway Postgres 17 (pgvector image, `unaccent` extension, which handles Vietnamese: `Việt Đức học` becomes `Viet Duc hoc`). 416 answerable questions (208 `seen`, 208 `blind`); a hit is a top-k chunk containing the question's evidence sentence. Two query sets: the questions as written, and the same questions with every accent removed. Keyword leg only here; the fused result is in the next subsection. Hit@5 in percent, 95% bootstrap interval for Hit@5 in brackets:

| Query set | Leg | A (today) Hit@5 | B (unaccent) Hit@5 | A Hit@1 | B Hit@1 |
|---|---|---|---|---|---|
| accented | `ts_rank_cd` | 63.0 [58.2, 67.5] | 58.2 [53.6, 63.0] | 39.9 | 34.6 |
| accented | BM25 | 88.9 [85.8, 91.8] | 79.6 [75.7, 83.4] | 69.7 | 60.6 |
| stripped | `ts_rank_cd` | 15.9 [12.5, 19.5] | 58.2 [53.6, 63.0] | 5.5 | 34.6 |
| stripped | BM25 | 25.0 [20.9, 29.3] | 79.6 [75.7, 83.4] | 9.6 | 60.6 |

By question kind (BM25 Hit@5, `seen` / `blind`): accented A 91.8 / 86.1, B 86.5 / 72.6; stripped A 25.5 / 24.5, B 86.5 / 72.6. The set has no other question types. Latency of the `ts_rank_cd` leg per query, 416 questions, warm, local: A 13.8 ms median and 25.2 ms p95; B 14.9 and 30.6 ms (the `unaccent` call on the query is inline). The `unaccent` GIN index is smaller (475 KB against 623 KB) because accent variants merge into one lexeme.

**What it shows.** On queries typed with accents, which is how these questions were written, unaccent makes retrieval worse: BM25 Hit@5 drops 9.3 points (88.9 to 79.6, intervals just touching), and per question 29 hits are lost against 9 gained for `ts_rank_cd`. Vietnamese accents separate words (`sử` history, `sự` fact; `ma`, `má`, `mà`, `mả`, `mạ`), so removing them adds false matches and the right chunk ranks lower. On queries typed without accents the effect reverses: today's leg finds the right chunk in only 16 to 25% of questions (it cannot match `hoc` to `học`), and B recovers 58 to 80%, close to its own accented result because stripped and accented queries become the same string. 180 questions gain a hit and 4 lose one for `ts_rank_cd`.

**What it does not show.** One book, 359 chunks, questions written by an LLM in accented Vietnamese and then stripped by a script: real users who drop accents also make other typing changes, and the share of users who do is unknown. The fused result with the dense leg was not measured; dense search already handles missing accents to some degree, so the gain in the fused system is probably smaller than the keyword-leg gain here, and the loss on accented queries is probably also smaller. The measured trade is therefore: unaccent only (B) trades about 9 points on accented queries for about 55 points on stripped ones. A middle option not measured here is to keep both columns and fuse them (or use the unaccented leg only when the query has no accents); that needs its own measurement. Word segmentation (the second part of #95, pyvi or underthesea) was not tried: it would add a dependency, which this measurement step does not do.

### Fused with the dense leg (#95)

[fts_unaccent_fused.py](../../experiments/e2e/fts_unaccent_fused.py) adds the dense leg to the same measurement ([fts-unaccent-fused-95.json](../../experiments/e2e/results/fts-unaccent-fused-95.json)): Ollama bge-m3 embeddings of the 359 chunks and of each question (exact cosine in numpy, which gives the order of the app's HNSW search with `strict_order`), 30 candidates per leg, RRF with k 60 as in `book_rag.retrieval.fusion`. The dense leg is the same in both arms (a stripped question is embedded as stripped); only the keyword column differs. Same 416 questions and the same two query sets. Hit@5 in percent with the 95% interval, and Hit@1:

| Query set | Result | Hit@1 | Hit@5 |
|---|---|---|---|
| accented | dense only | 61.3 | 86.5 [83.2, 89.7] |
| accented | A BM25 + dense (`simple`) | 67.3 | 90.6 [87.7, 93.3] |
| accented | B BM25 + dense (`unaccent`) | 66.3 | 88.9 [85.8, 91.8] |
| accented | A `ts_rank_cd` + dense | 50.7 | 79.3 [75.5, 83.2] |
| accented | B `ts_rank_cd` + dense | 49.8 | 75.7 [71.4, 79.8] |
| stripped | dense only | 15.6 | 36.1 [31.5, 40.9] |
| stripped | A BM25 + dense (`simple`) | 19.5 | 39.9 [35.1, 44.7] |
| stripped | B BM25 + dense (`unaccent`) | 33.9 | 69.7 [65.4, 74.0] |
| stripped | A `ts_rank_cd` + dense | 13.7 | 33.9 [29.3, 38.5] |
| stripped | B `ts_rank_cd` + dense | 28.4 | 56.5 [51.9, 61.3] |

BM25 here is the in-memory BM25 over Postgres lexemes (the ranking ceiling of the shipped leg, as above); `ts_rank_cd` is the SQL leg before ADR 0011. By kind (BM25 + dense, Hit@5, `seen` / `blind`): accented A 91.8 / 89.4, B 91.3 / 86.5; stripped A 41.8 / 38.0, B 72.1 / 67.3. The json also holds each leg alone and the per-question gain and loss counts.

**Reading.** Fused, unaccent costs 1.7 points of Hit@5 on accented questions (90.6 to 88.9, intervals overlap; 3.6 points for `ts_rank_cd`), against 9.3 for the keyword leg alone, because the dense leg covers most of what the accent-stripped column loses. On stripped questions it still adds 29.8 points (39.9 to 69.7; 22.6 for `ts_rank_cd`): the dense leg alone finds only 36%, so it does not make up for a keyword leg that cannot match `hoc` to `học`. Stripped questions are LLM-written accented questions with a script removing accents, the same limit as above. On accented questions, dense alone (86.5) is below A BM25 + dense (90.6) and close to B (88.9), so the keyword leg adds 2.4 to 4.1 points over dense alone at this book size. Cost of the `unaccent` column: unchanged from the keyword-only section (14.9 against 13.8 ms median for `ts_rank_cd`, a GIN index 24% smaller, a second column to store). Not measured: both columns fused as separate legs, which this run did not include.

## What follows

- Adopting any of these changes the search design, so it needs an ADR, and the choice is a latency-against-quality trade that is the user's to weigh: BM25 in Postgres restores the 11 points but multiplies the leg's time by about 5 on this book. Follow-up issue: bound the candidate set (for example, take the GIN matches on only the query's rarest words) and re-time.
- The reranker (ADR 0009) still hides the gap when it works; the fix matters when it is off or fails, and for Hit@1 before reranking.
- The end-to-end re-measurement with the reranker off and on, listed in #204, was made on 2026-11-14 at `e0bb10a` (#241): through the app, Hit@5 is 86.5% without the reranker and 94.2% with it (was 75.5% and 88.9%); Hit@1 is 64.9% and 84.1% (was 47.6% and 80.8%). See [e2e-real-model.md](e2e-real-model.md).

## Limits

One book (two chunkings of it), 208 synthetic questions, one run; latency from one local machine, Postgres in Docker, 392 chunks, so the growth rate with book size is argued, not measured. The intervals are bootstrap over questions. Reproduce as in [retrieval-gap.md](retrieval-gap.md), with `fts_options.py` in place of `gap.py`.
