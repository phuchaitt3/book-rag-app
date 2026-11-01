# 0002: PostgreSQL with pgvector and full-text search, no separate vector database

**Status:** Accepted   **Date:** 2026-10-30
**Decided by:** agents (before study-design mode)   **Confidence:** medium
**Review:** [#35](https://github.com/phuchaitt3/book-rag-app/issues/35), open   **Study note:** [docs/design/0002-postgres-pgvector-hybrid-search.md](../design/0002-postgres-pgvector-hybrid-search.md)

## Context

Answering a question about a book needs two kinds of retrieval over the book's chunks: semantic search over embedding vectors and keyword search over the words, merged (hybrid search). The app also stores relational data (books, sections, chunks, ingestion jobs). A chunk, its vector and its keyword data should be written together, all or nothing.

Estimates, not measurements (2026-10-31): about 10 books and 10,000 chunks now (about 40 MB of 1024-number vectors); about 10 million chunks and 40 GB at 1000x. Every search is limited to one book today, so a query ranks about 1,000 chunks. Constraints: a free or near-free production tier, one developer, local setup from one `docker compose up`. The first books are Vietnamese, for which Postgres has no text-search configuration. The README goals apply: scalability and operability before features, claims measured, not assumed.

## Options considered

- **A. Postgres with pgvector and built-in full-text search.** One system; a chunk, its vector and keywords are one row. A general database, so less tuning and raw speed than a search engine.
- **B. Postgres plus a dedicated vector database** (Qdrant, Weaviate, Pinecone). Better tuning, quantization and sharding. Two stores to keep consistent, another service and bill.
- **C. Elasticsearch or OpenSearch for both searches.** Best keyword search. Heavy to run, and Postgres is still needed, so it is B with a bigger service.
- **D. An in-process library (FAISS) with SQLite or files.** No server, but the index is per process and has no transactions with the metadata.

The full comparison is in the study note.

## Decision

Use PostgreSQL with `pgvector` (an HNSW index with cosine distance on `vector(1024)`) and `simple` full-text search in one database (option A). Retrieval stays behind the `ChunkSearcher` interface, so a dedicated store can be added later without touching callers.

## Why

At about 10,000 chunks one small Postgres does all of this, and it stays comfortable to roughly 100x that. A second store costs real consistency work, and in one database "this chunk and its vector exist" can be a transaction. The decision is about order, not a verdict on option B: given the project's goals, a dedicated store is added when a measurement calls for it, and trying it earlier as an experiment is welcome (ADR 0008).

HNSW rather than IVFFlat because it needs no training data and so works on a table that fills as books arrive. `simple` because it works for any language; vector search with bge-m3 carries the Vietnamese meaning, and keyword search is for names, numbers and exact phrases. Rankings are merged with Reciprocal Rank Fusion, which uses positions, not the incompatible scores.

The decision rests on these assumptions, all estimates: the corpus sizes above, a few queries per minute, and one book per query. It would change if the index stops fitting in memory (somewhere past 100x), if a measured p95 search latency fails a target (none is set yet), or if the eval set (ADR 0005) shows `simple` keyword search hurting Vietnamese questions.

## Consequences

- Easier: one thing to run, back up and monitor; local and production use the same engine; filtering by book or page is a `WHERE`; deleting a book cascades.
- The embedding dimension is part of the schema. Changing the model needs a migration and re-embedding every chunk.
- Filtering and the approximate index interact. Measured 2026-10-31 on synthetic data: the planner currently uses the exact `book_id` path and loses no rows, but with only the HNSW index a query returned 0.5 of 30 rows on average. The query sets `hnsw.iterative_scan = strict_order` as a safeguard ([#84](https://github.com/phuchaitt3/book-rag-app/issues/84)); it is bounded and untested at millions of rows (study note, "Measurements").
- Keyword search is accent-sensitive and does not segment Vietnamese words; only vector search covers those cases. Fixes in order of cost: an `unaccent` column, a word segmenter, a BM25 extension.
- Search load competes with ingestion and the job queue for the same database. The `pgvector` extension must exist on every host.
- The worker does not yet write a book atomically; the chat endpoint does not check ingestion succeeded ([#81](https://github.com/phuchaitt3/book-rag-app/issues/81)).
- Next steps as load grows, cheapest first: pooling and a read replica; partitioning by book; `halfvec`; a dedicated store behind `ChunkSearcher`, which this decision allows and ADR 0008 tests. Searching across several books ([#89](https://github.com/phuchaitt3/book-rag-app/issues/89)) would change the first two.

## Change log

- 2026-10-31: added the hybrid-search background, the Vietnamese `simple` explanation, the single-database point and the half-written example in answer to review questions ([#35](https://github.com/phuchaitt3/book-rag-app/issues/35)).
- 2026-10-31: recorded that the worker's batched commits are not all-or-nothing ([#81](https://github.com/phuchaitt3/book-rag-app/issues/81)); the one-book limit is not a design property ([#89](https://github.com/phuchaitt3/book-rag-app/issues/89)).
- 2026-10-31: option B marked "not chosen yet, not rejected", and the decision framed as an order, not a verdict ([#35](https://github.com/phuchaitt3/book-rag-app/issues/35), [#90](https://github.com/phuchaitt3/book-rag-app/issues/90)).
- 2026-10-31: added the `hnsw.iterative_scan` safeguard after the filtering measurement ([#63](https://github.com/phuchaitt3/book-rag-app/issues/63), [#84](https://github.com/phuchaitt3/book-rag-app/issues/84)).
- 2026-11-01: rewritten to the short template; teaching, options in depth, measurement and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
