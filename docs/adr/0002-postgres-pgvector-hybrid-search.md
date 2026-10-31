# 0002: PostgreSQL with pgvector and full-text search

**Status:** Accepted

**Decided by:** agents (decided and built before study-design mode; rewritten to the full template on 2026-10-31, the decision itself unchanged)   **Review:** [#35](https://github.com/phuchaitt3/book-rag-app/issues/35), open

## Context

The app answers questions about a book by finding the passages ("chunks") most relevant to the question and handing them to a language model. Finding them is *retrieval*, and it needs two kinds of matching:

- **Semantic (vector) search.** An *embedding model* (here bge-m3) turns each chunk and each question into a list of numbers, a *vector*, so that texts with similar meaning get vectors that are close together. Search means "find the chunks whose vectors are closest to the question's vector". This finds a passage about "feeling tired after lunch" for the question "why do I get sleepy after eating?", where no word is shared.
- **Keyword (full-text) search.** Matches the actual words. It is better than vectors for names, numbers, rare terms and exact phrases ("Chapter 7", a person's name), which embeddings often blur.

Using both and merging the results is called *hybrid search*. Vietnamese books are the first target, which matters because Postgres has no ready-made Vietnamese stemmer for keyword search (see "Why").

Besides search, the system stores ordinary relational data: books, a section tree, chunks with page numbers, and ingestion jobs. A chunk and its metadata must be written together and never half-written.

Numbers (estimates, not measurements; the real corpus is small):

| | Now | At 1000x |
|---|---|---|
| Books | about 10 | about 10,000 |
| Chunks per book | about 1,000 (a 400-page book cut into pieces of roughly 500 tokens) | same |
| Chunks in total | about 10,000 | about 10,000,000 |
| Vector storage | a vector of 1024 numbers at 4 bytes each is about 4 KB, so about 40 MB | about 40 GB, plus an index of similar size |
| Search traffic | a few queries per minute | tens of queries per second |
| Quality target | the right passage in the top 8 results; judged later by an eval set (ADR 0005) | same |

Every search is limited to one book (`WHERE book_id = ...`), so a query ranks about 1,000 chunks, not all of them. This shapes the decision below.

Constraints: a free or near-free production tier, one developer, and a local setup that runs from one `docker compose up`.

## Options considered

**A. PostgreSQL with pgvector and built-in full-text search (chosen).**
`pgvector` is a Postgres extension that adds a `vector` column type and distance operators. Postgres full-text search turns text into a `tsvector` (a sorted list of the words in it) and matches queries against it using a GIN index (an index from each word to the rows containing it).
- Pros: one system to run, back up and secure. A chunk, its vector and its keyword data are one row, so they are written in one transaction and filtered with ordinary SQL (`book_id`, `page`). Hosted Postgres with pgvector is widely available, including Neon, the production target. The same database also holds the job queue (ADR 0004) and users (ADR 0006).
- Cons: Postgres is a general database, not a search engine. Its vector index has fewer tuning options and less raw speed than a dedicated engine, and its keyword ranking is simpler than BM25 (the standard ranking formula, which weighs rare words more and discounts long documents). Search shares CPU, memory and connections with everything else.
- Cost: free locally; production is whatever the Neon plan costs, with no second bill.

**B. Postgres for the relational data plus a dedicated vector database (Qdrant, Weaviate, Pinecone).**
A purpose-built engine stores vectors and answers nearest-neighbour queries, often with built-in hybrid search and metadata filtering.
- Pros: finer recall-versus-speed tuning, quantization (storing vectors in fewer bytes), and sharding for hundreds of millions of vectors. Managed offerings remove operations work.
- Cons: two systems that must be kept in step. A chunk lives in Postgres and its vector elsewhere, so a failed write leaves them out of sync, and every ingestion needs a way to detect and repair that (the job in ADR 0004 would write to two places). Another service to run locally, another bill or free-tier limit in production, another network hop per query.
- Cost: a managed tier or a second container; at the current size nothing is gained for it.

**C. Elasticsearch or OpenSearch for both keyword and vector search.**
A search engine with real BM25, per-language analyzers, and vector fields.
- Pros: the best keyword search and mature hybrid features.
- Cons: heavy to run (a JVM service that wants GBs of memory), and Postgres is still needed for the relational data, so it is option B with a bigger service. No free hosting fits.

**D. A library inside the app process (FAISS, or vectors in memory) with SQLite or files.**
- Pros: no server at all.
- Cons: the index lives in one process, so it disappears on restart unless rebuilt or saved, can't be shared by several API instances, and gives up transactions with the metadata. It does not fit scaling by adding stateless API containers.

## Decision

Use PostgreSQL with `pgvector` and Postgres full-text search in one database (option A).

What is built (checked against `main`: `apps/api/migrations/versions/0001_initial_schema.py` and `apps/api/src/book_rag_api/retrieval.py`):
- The `chunks` table has an `embedding vector(1024)` column (bge-m3 produces 1024 numbers) and a `tsv` column that Postgres computes itself from `text` (`to_tsvector('simple', text)`, a generated column, so it cannot drift out of sync with the text).
- The vector column has an **HNSW index** with cosine distance (`vector_cosine_ops`), `m = 16`, `ef_construction = 64`. The `tsv` column has a GIN index.
- Both searches filter by `book_id` and return up to 30 candidates. The vector search orders by cosine distance; the keyword search matches any query word and orders by `ts_rank_cd`. `packages/rag` merges the two lists with Reciprocal Rank Fusion and optionally reranks them (see "Why").
- Locally the database is `pgvector/pgvector:pg17` in Docker Compose; in production it is Neon.

## Why

**Why one database (A over B, C, D).** At about 10,000 chunks, even 1000x that is a modest load for one well-sized Postgres, so what a dedicated engine buys (sharding, quantization, the fastest possible search) is not needed. What it costs is real: two stores to keep consistent, and consistency is where hand-built systems break. In one database, "this chunk and its vector exist" is a transaction, and "chunks from book X with page > 100" is a `WHERE`. This is the usual advice for a corpus below tens of millions of vectors, and it keeps the exit open: retrieval sits behind the `ChunkSearcher` interface in `packages/rag` (see ADR 0003), so a dedicated store can replace the Postgres one without touching callers. The decision rests on the table above; if the corpus grows by more than about 100x, revisit it.

**Why HNSW, not IVFFlat (the other pgvector index).** An exact nearest-neighbour search compares the query with every vector, which is slow at scale, so both index types are *approximate*: they sometimes miss a true neighbour, and the share they find is the *recall*.
- *IVFFlat* clusters the vectors, then searches only the nearest few clusters. It builds fast and is small, but it needs existing data to build good clusters, and its recall drops as data is added without a rebuild.
- *HNSW* (Hierarchical Navigable Small World) builds a layered graph in which each vector links to near neighbours; a search walks the graph toward the query. It gives better recall at the same speed and needs no training data, so it works on an empty table that fills as books are ingested. It costs more memory and slower builds, both small at this size.
- `m` is how many links each vector keeps (16 is pgvector's default) and `ef_construction` is how widely it looks for neighbours while inserting (64 is the default). Higher values raise recall and build time. These are untuned defaults, not measured choices. Query-time breadth is `hnsw.ef_search` (default 40), which nothing in this repo sets.
- Cosine distance, because embeddings are compared by direction, not length.

**Why `simple` for full-text search.** A text-search *configuration* decides how text is split into words and normalised. Postgres ships stemmers (reducing "running" to "run") for English and other languages, but none for Vietnamese. `simple` only lowercases and splits on non-letters, so it works for any language, at the price of no stemming and no stop-word removal. Accents are kept, so a query typed without diacritics does not match text that has them.

**Why combine with RRF.** The two searches give scores on different scales (a cosine distance and a text rank), so adding them directly is meaningless. *Reciprocal Rank Fusion* ignores scores and uses only positions: an item scores the sum of `1 / (60 + rank)` over each list it appears in, so an item ranked high in both lists wins and an item in one list still counts. The constant 60 is the one from the original paper. A *reranker* (a second model that reads the question together with each candidate and scores the pair) can then reorder the merged list; it is more accurate than either search but too slow to run on every chunk. Whether it is worth its cost is a question for the evals (ADR 0005).

## Consequences

Easier:
- One thing to run, back up, restore and monitor. Local and production use the same engine; only the host differs.
- Chunk, vector and keyword data are one row; ingestion (ADR 0004) writes them in one transaction, and deleting a book removes everything with it (`ON DELETE CASCADE`).
- Filtering by book, page or section is a plain `WHERE`.

Harder or committed to:
- **The embedding dimension is part of the schema.** `vector(1024)` ties the table to bge-m3. A model with a different dimension (a hosted embedder, for example) needs a migration to a new column or table, and *every* chunk must be embedded again, since vectors from different models can't be compared. The `Embedder` interface reports its `dimension` and the Ollama provider rejects vectors of the wrong length, so a mismatch fails loudly instead of corrupting data. The re-embedding cost (time, or API spend) is the real price of changing.
- **Filtering and the approximate index interact.** With `WHERE book_id = ... ORDER BY distance LIMIT 30`, pgvector may walk the HNSW index first and drop rows from other books afterwards, so a query on a small book can return fewer than 30 rows even though more exist. Because each book has only about 1,000 chunks, an exact scan of one book's rows may be as fast and more accurate, and the planner may already choose it. This is not measured yet; it is tracked in [#63](https://github.com/phuchaitt3/book-rag-app/issues/63) and does not change the decision.
- Keyword ranking is `ts_rank_cd`, which rewards matched words that sit close together but has no corpus-wide weighting of rare words. Fusion with vectors softens this. If keyword quality matters, a BM25 extension for Postgres is the next step before leaving Postgres.
- Search load competes with ingestion and the job queue for the same database's CPU, memory and connections.
- The `pgvector` extension must exist on every host. Neon supports it; a different host must be checked first.

## At 1000x the load

Roughly 10 million chunks, 40 GB of raw vectors, and tens of queries per second.

What breaks first, in order:
1. **Memory.** HNSW is fast when the graph fits in RAM. At 40 GB of vectors plus a similar index, a small Neon instance cannot hold it, queries start reading from disk, and latency jumps from milliseconds to hundreds of milliseconds.
2. **Index build and ingestion.** Building or rebuilding the HNSW index over millions of rows takes hours and a lot of memory, and inserting into a large graph slows down.
3. **Query concurrency.** Search shares CPU and connections with everything else. Connection pooling and a read replica (a second copy that serves only searches) are the first, cheap steps.

Next steps, cheapest first:
- *Partition* the table by book (split it into per-book pieces) so each query touches one small piece and can use an exact scan. This works because no query crosses books.
- Store vectors in fewer bytes (pgvector's `halfvec` uses 2 bytes per number, half the memory) or use fewer dimensions.
- Move the vectors to a dedicated store behind `ChunkSearcher`, keeping Postgres as the source of truth for text and metadata; the vector store is then a derived copy that can be rebuilt from Postgres. This is option B, taken only when the numbers above force it.

If a feature ever needs search across all books at once, the per-book trick stops working and the memory problem arrives earlier.

## Read more

- pgvector README, sections on HNSW, IVFFlat and filtering: https://github.com/pgvector/pgvector
- PostgreSQL documentation, chapter "Full Text Search" (tsvector, configurations, GIN, `ts_rank_cd`): https://www.postgresql.org/docs/current/textsearch.html
- Malkov and Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (the HNSW paper): https://arxiv.org/abs/1603.09320
- Cormack, Clarke and Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods" (SIGIR 2009), the paper behind the fusion step.

## Review

Questions and answers go here, dated, from [#35](https://github.com/phuchaitt3/book-rag-app/issues/35). None yet.
