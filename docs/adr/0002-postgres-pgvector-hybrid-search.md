# 0002: PostgreSQL with pgvector and full-text search

**Status:** Accepted

**Decided by:** agents (decided and built before study-design mode; rewritten to the full template on 2026-10-31, the decision itself unchanged)   **Review:** [#35](https://github.com/phuchaitt3/book-rag-app/issues/35), open

## Context

The app answers questions about a book by finding the passages ("chunks") most relevant to the question and handing them to a language model. Finding them is *retrieval*, and it needs two kinds of matching:

- **Semantic (vector) search.** An *embedding model* (here bge-m3) turns each chunk and each question into a list of numbers, a *vector*, so that texts with similar meaning get vectors that are close together. Search means "find the chunks whose vectors are closest to the question's vector". This finds a passage about "feeling tired after lunch" for the question "why do I get sleepy after eating?", where no word is shared.
- **Keyword (full-text) search.** Matches the actual words. It is better than vectors for names, numbers, rare terms and exact phrases ("Chapter 7", a person's name), which embeddings often blur.

Using both and merging the results is called *hybrid search*. It is a common default for retrieval systems today: Elasticsearch, Weaviate, Qdrant, Vespa and Azure AI Search all offer it, and Anthropic's "Contextual Retrieval" write-up combines embeddings with BM25 keyword search for the same reason. Its appeal is that the two methods fail on different questions, and merging them needs no training and little code. This repo has not measured the gain on its own books; the eval set (ADR 0005) is where that gets checked.

Vietnamese books are the first target, and that makes keyword search harder than in English. Postgres has no Vietnamese configuration, and the usual fix for English, a *stemmer*, is not the main need for Vietnamese. "Why `simple` for full-text search" below explains what is missing and what it costs.

Besides search, the system stores ordinary relational data: books, a section tree, chunks with page numbers, and ingestion jobs. All of it, the search data included, lives in the same PostgreSQL database; that is the central choice of this ADR, and option B below is the alternative of keeping the vectors in a separate store.

A chunk and its metadata must be written together and never half-written. "Half-written" means a write that stops partway. Ingesting one book inserts about 1,000 chunks, and each needs its text, page number, section link, embedding vector and keyword data. If the worker crashed or lost its connection after 400 chunks, or after a chunk's text was saved but before its vector was, the book would be left in a broken state: chunks with no vector are never returned by vector search, and nothing raises an error, so answers are quietly worse. The ideal is "all or nothing": either the whole write happens and is visible, or none of it is. A database *transaction* provides exactly that, and only a single database can give it across a chunk and its vector (see option B for what goes wrong with two).

**The ingestion worker does not currently do this.** `apps/worker/src/book_rag_worker/ingest.py` commits the chunk text first, then writes the embeddings in batches of 32 with one commit per batch, so the API can show progress. Until the last batch commits, some chunks have `embedding IS NULL`, and a crash in between leaves exactly the half-written book described above. The chat endpoint checks that the book exists but not that its ingestion job succeeded, so such a book is searched without any warning. A single database makes the fix easy (a `ready` flag on the book set in a last step, or a check of the job status), but it is not in place yet; it is tracked in [#81](https://github.com/phuchaitt3/book-rag-app/issues/81).

Numbers (estimates, not measurements; the real corpus is small):

| | Now | At 1000x |
|---|---|---|
| Books | about 10 | about 10,000 |
| Chunks per book | about 1,000 (a 400-page book cut into pieces of at most 1,200 characters, about 300 tokens) | same |
| Chunks in total | about 10,000 | about 10,000,000 |
| Vector storage | a vector of 1024 numbers at 4 bytes each is about 4 KB, so about 40 MB | about 40 GB, plus an index of similar size |
| Search traffic | a few queries per minute (assumed) | tens of queries per second (assumed) |
| Quality target | the right passage in the top 8 results (an assumed target; the retriever's default `top_k` is 8 and the chat endpoint's is 6), judged later by an eval set (ADR 0005) | same |

The corpus sizes, traffic and quality target are assumptions made when this ADR was written, not measurements or numbers set elsewhere in the repo.

Every search is limited to one book (`WHERE book_id = ...`), so a query ranks about 1,000 chunks, not all of them. This shapes the decision below.

Constraints: a free or near-free production tier, one developer, and a local setup that runs from one `docker compose up`.

## Options considered

**A. PostgreSQL with pgvector and built-in full-text search (chosen).**
`pgvector` is a Postgres extension that adds a `vector` column type and distance operators. Postgres full-text search turns text into a `tsvector` (a sorted list of the words in it) and matches queries against it using a GIN index (an index from each word to the rows containing it).
- Pros: one system to run, back up and secure. A chunk, its vector and its keyword data are one row, so a single write can cover all three (the worker currently commits the vectors in later batches, see "Context" and [#81](https://github.com/phuchaitt3/book-rag-app/issues/81)), and they are filtered with ordinary SQL (`book_id`, `page`). Hosted Postgres with pgvector is widely available, including Neon, the production target. The same database also holds the job queue (ADR 0004) and users (ADR 0006).
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
- The vector query runs `SET LOCAL hnsw.iterative_scan = strict_order` first, so that if the planner ever uses only the HNSW index, the index walk continues until 30 rows of the wanted book are found instead of returning almost none (see the measurement in "Consequences"). `strict_order` keeps the exact distance order that rank fusion relies on. The setting needs pgvector 0.8 or later, so the searcher reads the installed `vector` extension version once and skips the setting on older ones. Neon's extensions page lists pgvector 0.8.0 for PostgreSQL 17 (read 2026-10-31); the local Docker image has 0.8.7 at the time of writing.
- Locally the database is `pgvector/pgvector:pg17` in Docker Compose; in production it is Neon.

## Why

**Why one database (A over B, C, D).** At about 10,000 chunks (40 MB of vectors) one small Postgres does all of this easily, and it stays comfortable up to roughly 100x that, about 1 million chunks and 4 GB of vectors, which fits in the memory of a mid-sized instance. Up to there, what a dedicated engine buys (sharding, quantization, the fastest possible search) is not needed. At 1000x the picture changes, as "At 1000x the load" below shows: the index no longer fits in memory on a small instance, and the cheaper fixes there come before a dedicated store. What a second store costs is real: two stores to keep consistent, and consistency is where hand-built systems break. In one database, "this chunk and its vector exist" can be a transaction (the worker does not yet use one for this, see "Context"), and "chunks from book X with page > 100" is a `WHERE`. This is the usual advice for a corpus below tens of millions of vectors, and it keeps the exit open: retrieval sits behind the `ChunkSearcher` interface in `packages/rag` (see ADR 0003), so a dedicated store can replace the Postgres one without touching callers. The decision rests on the table above. The trigger to revisit it is the first failure in "At 1000x the load" (the index stops fitting in memory), which the table puts at somewhere past 100x; measure memory use and search latency as the corpus grows instead of waiting for the number.

**Why HNSW, not IVFFlat (the other pgvector index).** An exact nearest-neighbour search compares the query with every vector, which is slow at scale, so both index types are *approximate*: they sometimes miss a true neighbour, and the share they find is the *recall*.
- *IVFFlat* clusters the vectors, then searches only the nearest few clusters. It builds fast and is small, but it needs existing data to build good clusters, and its recall drops as data is added without a rebuild.
- *HNSW* (Hierarchical Navigable Small World) builds a layered graph in which each vector links to near neighbours; a search walks the graph toward the query. It gives better recall at the same speed and needs no training data, so it works on an empty table that fills as books are ingested. It costs more memory and slower builds, both small at this size.
- `m` is how many links each vector keeps (16 is pgvector's default) and `ef_construction` is how widely it looks for neighbours while inserting (64 is the default). Higher values raise recall and build time. These are untuned defaults, not measured choices. Query-time breadth is `hnsw.ef_search` (default 40), which nothing in this repo sets.
- Cosine distance, because embeddings are compared by direction, not length.

**Why `simple` for full-text search.** A text-search *configuration* decides how text is split into words and normalised. Postgres ships configurations for English and other languages that *stem* (reduce "running", "runs" and "ran" towards "run", so a query for one finds the others) and drop stop words ("the", "of"). It has none for Vietnamese. `simple` only lowercases and splits on non-letters, so it works for any language, at the price of no stemming and no stop-word removal.

For Vietnamese the missing stemmer matters less than it sounds, because Vietnamese words do not change form: there is no plural, tense or case ending to strip, so "học" (study) is the same string everywhere. Three other gaps matter more, and `simple` has all three:
- **Words are made of several syllables.** Vietnamese is written with a space between syllables, not between words. "học sinh" (student) is one word of two syllables, and "học" and "sinh" alone mean "study" and "born". `simple` sees two separate words. A keyword query for "học sinh" therefore matches any chunk that contains "học" or "sinh" anywhere, because the search matches any query word (see "What is built"); it does not look for the pair. Proper handling needs a *word segmenter* (a tool that groups syllables into words, such as VnCoreNLP or Underthesea) run on both the text and the query, which Postgres does not do and which would be a new dependency in the ingestion worker.
- **Diacritics.** Vietnamese marks tone and vowel quality with accents ("ma", "má", "mả", "mã", "mạ" and "mà" are different words). Many people type queries without accents, so "hoc sinh" should match "học sinh"; with `simple` it does not (see "Consequences", keyword search is accent-sensitive).
- **Stop words.** Very common syllables ("là", "của", "và") are not removed, so they match many chunks and add noise to the keyword list. BM25 or `ts_rank_cd` weighting reduces the harm but does not remove it.

Why accept this: vector search with bge-m3 is multilingual, understands Vietnamese meaning, and is not affected by accents or syllable splitting in this way, and it is the half of the hybrid that carries ordinary questions. Keyword search is there for names, numbers and exact phrases, where `simple` is adequate. Whether the gaps above hurt on real Vietnamese questions is something the eval set should show (ADR 0005); the fixes, in order of cost, are an `unaccent` column, then a segmenter plus a custom configuration, then a BM25 extension (see "Consequences").

**Why combine with RRF.** The two searches give scores on different scales (a cosine distance and a text rank), so adding them directly is meaningless. *Reciprocal Rank Fusion* ignores scores and uses only positions: an item scores the sum of `1 / (60 + rank)` over each list it appears in, so an item ranked high in both lists wins and an item in one list still counts. The constant 60 is the one from the original paper. A *reranker* (a second model that reads the question together with each candidate and scores the pair) can then reorder the merged list; it is more accurate than either search but too slow to run on every chunk. Whether it is worth its cost is a question for the evals (ADR 0005).

## Consequences

Easier:
- One thing to run, back up, restore and monitor. Local and production use the same engine; only the host differs.
- Chunk, vector and keyword data are one row; one transaction could cover them, though the worker commits the text first and the vectors in batches of 32 ([#81](https://github.com/phuchaitt3/book-rag-app/issues/81)), and deleting a book removes everything with it (`ON DELETE CASCADE`).
- Filtering by book, page or section is a plain `WHERE`.

Harder or committed to:
- **The embedding dimension is part of the schema.** `vector(1024)` ties the table to bge-m3. A model with a different dimension (a hosted embedder, for example) needs a migration to a new column or table, and *every* chunk must be embedded again, since vectors from different models can't be compared. The `Embedder` interface reports its `dimension` and the Ollama provider rejects vectors of the wrong length, so a mismatch fails loudly instead of corrupting data. The re-embedding cost (time, or API spend) is the real price of changing.
- **Filtering and the approximate index interact.** With `WHERE book_id = ... ORDER BY distance LIMIT 30`, pgvector may walk the HNSW index first and drop rows from other books afterwards, so a query on a small book can return fewer than 30 rows even though more exist. pgvector 0.8 and later also has *iterative index scans* (`hnsw.iterative_scan`), which keep walking the index until enough rows survive the filter. Which pgvector version runs is not pinned in this repo: the Docker tag `pgvector/pgvector:pg17` follows the latest release and Neon chooses its own, so check the version before relying on the setting.

  This was measured for [#63](https://github.com/phuchaitt3/book-rag-app/issues/63) on 2026-10-31 (pgvector 0.8.7, PostgreSQL 17, the schema from migration 0001, a throwaway local container). The data was synthetic: random 1024-dimension vectors, 1,000 chunks per book, 10 books (10,000 chunks) and then 100 books (100,000 chunks). Real embeddings are clustered by topic and language, so a query's neighbours are likely to come from its own book; the figures below, and the size of the filtering effect, are therefore unmeasured on real data and could differ in either direction.
  - **What the planner does today:** for the app's exact query it ignores the HNSW index and uses the `book_id` index, reads the book's 1,000 rows and sorts them by distance (a bitmap scan plus a top-N sort). It returned 30 rows, exactly nearest, in about 8 ms with 10 books and about 29 ms with 100 books. These two times are not comparable (the cache state of the first run was not recorded, the second was a first, cold run, and a repeat took about 4 ms), so do not read a scaling trend from them. The table also has a second index starting with `book_id` (the unique constraint on `book_id, ordinal`), so either can serve.
  - **When only the HNSW index is available** (measured by dropping both `book_id` indexes inside a transaction that was rolled back): the planner walks the HNSW graph and discards other books' rows. The sample query returned **0 rows**; over 20 random queries on 20 books the average was **0.5 rows of the 30 asked for**. With the default `hnsw.ef_search` of 40, the graph walk only looks at about 40 candidates, and almost none belong to the wanted book.
  - **With `hnsw.iterative_scan` set to `strict_order` or `relaxed_order`:** every query returned 30 rows.
  - **Conclusion:** no rows are lost today, because the planner picks the exact `book_id` path, which is also the most accurate. But that is the planner's choice, not a guarantee. The failure case was produced by removing both `book_id` indexes, so the idea that a change in table size or statistics could flip the choice is an inference, not a measurement. Not measured: tables of millions of rows, where the planner's choice may differ. The decision is unchanged, and the safeguard is now part of it: see "Decision" (implemented in [#84](https://github.com/phuchaitt3/book-rag-app/issues/84)).
- **Keyword search is accent-sensitive.** The `simple` configuration has no `unaccent` step, so a query for "hoc sinh" does not match "học sinh" in keyword search, and only vector search covers that case for Vietnamese. The mitigation is a second generated column that runs `unaccent` over the text (and the same on the query), at the cost of a schema migration and a larger index.
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

Questions and answers go here, dated, from [#35](https://github.com/phuchaitt3/book-rag-app/issues/35).

**2026-10-31, owner:** Is hybrid search the most popular approach currently, for its effectiveness and simplicity?
**Answer:** It is one of the most common defaults, not the only popular one; plain vector search is still widespread because it is the simplest. Hybrid is popular because it costs little extra (one more index and a merge step) and covers the cases where vectors are weak. "Most effective" is a claim to test here, not assume: see the paragraph on hybrid search in "Context". Changed: that paragraph.

**2026-10-31, owner:** Modify the ADR to explain the Vietnamese stemmer for keyword search in more detail.
**Answer:** Rewrote "Why `simple` for full-text search". The main point: Vietnamese does not need a stemmer much, since words do not inflect; the real gaps are multi-syllable words, accents and stop words. Changed: "Context" (summary line) and "Why `simple` for full-text search".

**2026-10-31, owner:** "Besides search, the system stores ordinary relational data..." Are these all stored inside a database together? Is this a design choice we should think about?
**Answer:** Yes to both: books, sections, chunks, vectors, keyword data and jobs are all in one PostgreSQL database, and it is the main design choice of this ADR (option A against option B). Made explicit in "Context". The decision stands because one database makes all-or-nothing writes possible (the worker does not use them yet, [#81](https://github.com/phuchaitt3/book-rag-app/issues/81)); the cost is that search shares the database's resources, covered in "At 1000x the load".

**2026-10-31, owner:** "A chunk and its metadata must be written together and never half-written." What does half-written mean? Update the ADR.
**Answer:** A write that stops partway, leaving some chunks or some of a chunk's fields saved. Added a worked example to "Context". Review of PR #80 found that the example is not only hypothetical: the worker commits vectors in batches, so "Context", option A and "Consequences" now say the all-or-nothing write is not in place; tracked in #81.
