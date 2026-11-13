# Study note: ranking keyword matches with BM25 inside Postgres

**For:** ADR 0011   **Status:** proposed in ADR 0011

## Problem

Hybrid search fuses a vector leg (meaning) with a keyword leg (exact words, names). The app's keyword leg ranks by how often the query words appear in a chunk, with every word counting the same. A question is mostly common words, so a chunk that repeats them can outrank the one holding the rare name. Measured, the leg alone finds the evidence in the top 5 for 58% of questions, and fusing it hurts ([retrieval-gap.md](../benchmarks/retrieval-gap.md)).

## Terms

- **Inverted index (GIN in Postgres):** a map from each word to the chunks containing it; it finds the chunks with a word without reading the others.
- **Term frequency (tf):** how many times a word occurs in one chunk. **Document frequency (df):** in how many chunks it occurs. **idf:** a weight that is high for rare words and near zero for words in most chunks.
- **BM25:** a score that sums, over the query's words, idf times a saturating function of tf, corrected for chunk length (parameters k1 and b). The long-standing default of search engines.
- **RRF (reciprocal rank fusion):** merges ranked lists by summing 1/(60+rank); it uses ranks only, so scores from different legs need no calibration.
- **Candidate set:** the chunks a leg scores. The cost grows with its size.

## Requirements

Lift the lexical leg to the benchmark's BM25 quality; keep it at or under today's 14 ms median at this size; do not let the cost grow with every chunk matching a common word; no new service.

## Options in depth

**Statistics per query.** The SQL unnests every chunk's `tsvector` to count words and lengths. No schema change and the right ranking, but O(book) per question: 80 ms here. Storing only df and lengths saves just 15%, because the work is scoring every chunk that matches any word, and an OR of a question matches nearly all of them.

**Stored statistics plus a rare-word candidate set (chosen).** df and chunk lengths are kept per book. The GIN index is asked only for the rarest words, so the candidate set is small; those chunks are then scored with all words. Measured on the PDF (392 chunks), median per question, fused with the dense leg:

| Rare means in at most | Median | Fused Hit@5 (PDF / HTML) | Leg alone Hit@5 (PDF) |
|---|---|---|---|
| 100% (no bound) | 26 ms | 86.5 / 89.4 | 84.1 |
| 50% | 26 ms | 86.5 / 89.4 | 84.1 |
| 20% | 11 ms | 86.5 / 88.9 | 83.7 |
| 10% | 5 ms | 85.6 / 88.0 | 76.4 |
| 5% | 2 ms | 83.7 / 86.5 | 62.0 |

The leg alone collapses faster than the fused result because the dense leg covers for it; the 20% row keeps the margin. Medians for the "no bound" row differ from the 69 ms in [fts-options.md](../benchmarks/fts-options.md) because the query here selects candidates with the index before unnesting.

**BM25 in the application.** Easy to unit-test, but the postings must live in process memory per book and be invalidated when a book is re-ingested, which fights the stateless-API goal unless a cache layer is added. Not measured.

**A BM25 extension or a search engine.** The best ranking and speed at scale, but not in the pgvector image and one more thing to run and keep in sync. This is the research in #90; it starts to win when books, or the number of books, outgrow rare-word candidates and a per-book term table.

## At 1000x the load

The term table grows with distinct words per book (about 8,000 rows for 392 chunks) times books; the candidate set grows with the number of chunks that hold a rare query word, so a very large book still scores many chunks. At that size the term table needs partitioning by book and the candidate set a hard cap; past that, an engine. Database CPU, not this leg, is the first limit on concurrency.

## Sources to read

- Robertson and Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond" (2009).
- The Postgres documentation, "Text Search Functions" (`ts_rank_cd`, `ts_stat`) and "GIN Indexes".
- Cormack, Clarke and Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods" (2009).
