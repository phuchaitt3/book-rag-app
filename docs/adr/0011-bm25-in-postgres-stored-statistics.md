# 0011: The full-text leg ranks with BM25 computed in Postgres from stored per-book statistics

**Status:** Proposed   **Date:** 2026-11-14
**Decided by:** agents   **Confidence:** medium
**Review:** [#209](https://github.com/phuchaitt3/book-rag-app/issues/209), open   **Study note:** [docs/design/0011-bm25-in-postgres.md](../design/0011-bm25-in-postgres.md)

## Context

[ADR 0002](0002-postgres-pgvector-hybrid-search.md) put keyword search in Postgres full-text search and listed real BM25 as a later option. The app's leg (`ts_rank_cd` over an OR query) has no document-frequency weighting; alone it finds the evidence in the top 5 for 58% of 208 questions, and fusing it makes the app worse than its dense leg alone (75.5% against 79.3% Hit@5; measured 2026-11-13, [retrieval-gap.md](../benchmarks/retrieval-gap.md)). With BM25 in its place the fused Hit@5 is 86.5% on the PDF and 89.4% on the HTML chunks (95% CI 81.7–90.9 and 85.1–93.3; measured 2026-11-14, [fts-options.md](../benchmarks/fts-options.md)). BM25 scored per query from the `tsvector` costs about 80 ms against 14 ms for today's leg at 392 chunks (same note). Scalability comes first in this project, so the cost must not grow with every chunk that matches a common word.

## Options considered

- **Word-dropping or `ts_rank_cd` flags.** Free, but 0.9 to 10 points short of BM25 in Hit@5 and about 8 to 14 short in Hit@1; the flags do not help.
- **BM25 in Postgres, statistics per query.** Right quality, 80 ms, linear in the book; the fallback.
- **BM25 in Postgres, stored statistics, candidates from rare words (chosen).** Same quality at a 20% cut-off (86.5% and 88.9% fused Hit@5), 11 ms median (measured, [fts-bounded-208.json](../../experiments/e2e/results/fts-bounded-208.json)).
- **BM25 in the application.** Needs postings cached per process and invalidated on ingest; not measured.
- **A BM25 extension or engine** ([#90](https://github.com/phuchaitt3/book-rag-app/issues/90)). Not measured; the Compose image has none.

## Decision

Store, per book, the token count of each chunk (`chunks.token_count`) and the document frequency of each term (`book_terms(book_id, term, df)`), written by the ingestion worker with the chunks. `text_search` takes the query's terms, selects the chunks the GIN index finds for the terms that occur in at most 20% of the book's chunks (all terms when none qualifies), and ranks them by BM25 (k1 1.2, b 0.75) over every query term, in one SQL statement.

## Why

It recovers the 11 points the full-text leg costs, keeps one database (ADR 0002), and bounds the scored set by the rare words, which is what makes it faster than today's OR of every word. At a 10% cut-off the leg loses recall (76.4% alone, 85.6% fused); at 20% it does not, so 20% is the setting with margin, not a tuned optimum. The answer changes if books grow until the term table or the rare-word candidates dominate (then an engine, #90), or if the stored statistics drift from the chunks (they are rebuilt per book on re-ingest).

## Consequences

- A migration adds `chunks.token_count` and `book_terms`, with a backfill for existing books; the term table is about 8,000 rows for a 392-chunk book (measured).
- Tokenisation stays Postgres's `simple` configuration, so accents are not folded ([#95](https://github.com/phuchaitt3/book-rag-app/issues/95)).
- One book and two chunkings were measured; growth with book size and with several books is argued, not measured ([#208](https://github.com/phuchaitt3/book-rag-app/issues/208)).
- Next step as load grows: partition or cap `book_terms`, then an engine.

## Change log

- 2026-11-14: proposed, with the measurements above ([#208](https://github.com/phuchaitt3/book-rag-app/issues/208)).
