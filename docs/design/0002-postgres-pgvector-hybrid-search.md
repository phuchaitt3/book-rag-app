# Study note: one Postgres for vectors, keywords and relational data

**For:** [ADR 0002](../adr/0002-postgres-pgvector-hybrid-search.md)   **Status:** decided in ADR 0002

This note holds the teaching material and the measurements behind ADR 0002. The ADR states the decision; this note explains the terms, compares the options in depth, records the measurement and works through what breaks at 1000x the load. It was moved out of the ADR on 2026-11-01 (#128); the text is the ADR's earlier wording, lightly trimmed.

## Problem

The app answers questions about a book by finding the passages ("chunks") most relevant to the question and handing them to a language model. Finding them is *retrieval*. The question is where to store and search the chunks, their vectors and their keyword data.

## Terms

- **Embedding and vector.** An *embedding model* (here bge-m3) turns each chunk and each question into a list of numbers, a *vector*, so that texts with similar meaning get vectors that are close together. Search means "find the chunks whose vectors are closest to the question's vector". This finds a passage about "feeling tired after lunch" for the question "why do I get sleepy after eating?", where no word is shared.
- **Keyword (full-text) search.** Matches the actual words. It is better than vectors for names, numbers, rare terms and exact phrases ("Chapter 7"), which embeddings often blur.
- **Hybrid search.** Using both and merging the results. It is a common default: Elasticsearch, Weaviate, Qdrant, Vespa and Azure AI Search all offer it, and Anthropic's "Contextual Retrieval" write-up combines embeddings with BM25 keyword search for the same reason. The two methods fail on different questions, and merging them needs no training and little code. Plain vector search is still widespread because it is the simplest. This repo has not measured the gain on its own books; the eval set (ADR 0005) is where that gets checked.
- **pgvector.** A Postgres extension that adds a `vector` column type and distance operators.
- **tsvector and GIN.** Postgres full-text search turns text into a `tsvector` (a sorted list of the words in it) and matches queries against it using a GIN index (an index from each word to the rows containing it).
- **BM25.** The standard keyword ranking formula; it weighs rare words more and discounts long documents. Postgres's `ts_rank_cd` rewards matched words that sit close together but has no corpus-wide weighting of rare words.
- **Transaction.** A database mechanism that makes a group of writes "all or nothing": either the whole write is visible or none of it is. Only a single database can give this across a chunk and its vector.
- **Approximate nearest neighbour, recall.** An exact search compares the query with every vector, which is slow at scale, so vector indexes are *approximate*: they sometimes miss a true neighbour. The share they find is the *recall*.
- **IVFFlat.** Clusters the vectors, then searches only the nearest few clusters. It builds fast and is small, but it needs existing data to build good clusters, and its recall drops as data is added without a rebuild.
- **HNSW** (Hierarchical Navigable Small World). A layered graph in which each vector links to near neighbours; a search walks the graph toward the query. Better recall at the same speed, and no training data needed, so it works on an empty table that fills as books are ingested. It costs more memory and slower builds, both small at this size. `m` is how many links each vector keeps (16 is pgvector's default); `ef_construction` is how widely it looks for neighbours while inserting (64 is the default). Query-time breadth is `hnsw.ef_search` (default 40).
- **Text-search configuration, stemmer, stop words.** A configuration decides how text is split into words and normalised. English and similar configurations *stem* (reduce "running", "runs" and "ran" towards "run") and drop stop words ("the", "of"). `simple` only lowercases and splits on non-letters, so it works for any language.
- **Reciprocal Rank Fusion (RRF).** Merges ranked lists by position only: an item scores the sum of `1 / (60 + rank)` over each list it appears in. The constant 60 is from the original paper.
- **Reranker.** A second model that reads the question together with each candidate and scores the pair. More accurate than either search, but too slow to run on every chunk.
- **Partitioning, halfvec.** Partitioning splits a table into per-key pieces (here per book). `halfvec` is pgvector's 2-bytes-per-number vector type.

## Requirements

Numbers are estimates, not measurements; the real corpus is small. Written 2026-10-31.

| | Now | At 1000x |
|---|---|---|
| Books | about 10 | about 10,000 |
| Chunks per book | about 1,000 (a 400-page book cut into pieces of at most 1,200 characters, about 300 tokens) | same |
| Chunks in total | about 10,000 | about 10,000,000 |
| Vector storage | 1024 numbers at 4 bytes is about 4 KB per vector, so about 40 MB | about 40 GB, plus an index of similar size |
| Search traffic | a few queries per minute (assumed) | tens of queries per second (assumed) |
| Quality target | the right passage in the top 8 results (assumed; the retriever's default `top_k` is 8, the chat endpoint's is 6), judged later by the eval set (ADR 0005) | same |

Other needs:

- Chunk, vector and keyword data must be written together, never half-written. Ingesting one book inserts about 1,000 chunks, each needing text, page number, section link, embedding and keyword data. If the worker crashed after 400 chunks, or after a chunk's text was saved but before its vector, the book would be broken: chunks with no vector are never returned by vector search and nothing raises an error, so answers are quietly worse. The worker does not yet write this atomically: it commits the text first, then the embeddings in batches of 32 so the API can show progress, and the chat endpoint does not check that ingestion succeeded ([#81](https://github.com/phuchaitt3/book-rag-app/issues/81)). A single database makes the fix easy (a `ready` flag set in a last step, or a job-status check).
- Every search is limited to one book today (`WHERE book_id = ...`; `POST /books/{book_id}/chat`), so a query ranks about 1,000 chunks. That is a property of the current product, not a law. A question over a few chosen books (`book_id = ANY(...)`) ranks a few thousand chunks, but with one global HNSW index it meets the same filtered-search problem as one book (below, [#63](https://github.com/phuchaitt3/book-rag-app/issues/63)), and whether partitioning helps depends on the planner pruning pieces for a parameter known only at run time, which is not checked. A question over every book grows the search to the whole corpus. Neither is measured; [#89](https://github.com/phuchaitt3/book-rag-app/issues/89) tracks the feature.
- Constraints: a free or near-free production tier, one developer, a local setup from one `docker compose up`. Project goals (README, "Goals and priorities"): scalability and operability before features, claims measured not assumed. Trying a dedicated store behind the interface is a legitimate learning goal, as long as it is compared with Postgres by numbers.

## Options in depth

**A. PostgreSQL with pgvector and built-in full-text search (chosen).**
- Pros: one system to run, back up and secure. A chunk, its vector and its keyword data are one row, filtered with ordinary SQL (`book_id`, `page`). Hosted Postgres with pgvector is widely available, including Neon, the production target. The same database holds the job queue (ADR 0004) and users (ADR 0006).
- Cons: a general database, not a search engine. Its vector index has fewer tuning options and less raw speed than a dedicated engine, and keyword ranking is simpler than BM25. Search shares CPU, memory and connections with everything else.
- Cost: free locally; production is the Neon plan, with no second bill.

**B. Postgres for relational data plus a dedicated vector database (Qdrant, Weaviate, Pinecone).**
- Pros: finer recall-versus-speed tuning, quantization (vectors in fewer bytes), sharding for hundreds of millions of vectors; managed offerings remove operations work.
- Cons: two systems to keep in step. A chunk lives in Postgres and its vector elsewhere, so a failed write leaves them out of sync, and ingestion needs a way to detect and repair that. Another service locally, another bill or free-tier limit in production, another network hop per query.
- Status: not chosen *yet*, not rejected. It is the planned scaling step and worth building as a bounded experiment before it is needed: a second `ChunkSearcher` with Postgres still the source of truth (research in [#90](https://github.com/phuchaitt3/book-rag-app/issues/90); the experiment is ADR 0008).

**C. Elasticsearch or OpenSearch for both keyword and vector search.**
- Pros: the best keyword search and mature hybrid features.
- Cons: heavy to run (a JVM service wanting GBs of memory), and Postgres is still needed for relational data, so it is option B with a bigger service. No free hosting fits.

**D. A library inside the app process (FAISS, or vectors in memory) with SQLite or files.**
- Pros: no server at all.
- Cons: the index lives in one process, so it disappears on restart unless rebuilt or saved, cannot be shared by several API instances, and gives up transactions with the metadata. It does not fit scaling by adding stateless API containers.

## What is built

Checked against `main` on 2026-10-31 (`apps/api/migrations/versions/0001_initial_schema.py`, `apps/api/src/book_rag_api/retrieval.py`):

- `chunks` has an `embedding vector(1024)` column (bge-m3 produces 1024 numbers) and a `tsv` column Postgres computes from `text` (`to_tsvector('simple', text)`, a generated column, so it cannot drift).
- An HNSW index with cosine distance (`vector_cosine_ops`), `m = 16`, `ef_construction = 64` (untuned defaults), and a GIN index on `tsv`. Cosine, because embeddings are compared by direction, not length.
- Both searches filter by `book_id` and return up to 30 candidates. The vector search orders by cosine distance; the keyword search matches any query word and orders by `ts_rank_cd`. `packages/rag` merges the lists with RRF and optionally reranks them. Whether the reranker is worth its cost is a question for the evals.
- The vector query runs `SET LOCAL hnsw.iterative_scan = strict_order` first, so if the planner uses only the HNSW index, the walk continues until 30 rows of the wanted book are found or `hnsw.max_scan_tuples` (20,000 by default) is reached. The walk is bounded: with millions of chunks it can still return fewer than 30 rows. The scale step is to raise `hnsw.max_scan_tuples`, or give each book its own partial index or partition. `strict_order` keeps the exact distance order that rank fusion relies on. The setting needs pgvector 0.8 or later, so the searcher reads the installed extension version once and skips the setting on older ones. Neon lists pgvector 0.8.0 for PostgreSQL 17 (read 2026-10-31); the local Docker image had 0.8.7.
- Locally `pgvector/pgvector:pg17` in Docker Compose; in production Neon.

## Why `simple` for full-text search, in depth

Postgres has no Vietnamese configuration, and Vietnamese books are the first target. For Vietnamese the missing stemmer matters less than it sounds, because words do not change form: there is no plural, tense or case ending to strip. Three other gaps matter more, and `simple` has all three:

- **Words are made of several syllables.** Vietnamese is written with a space between syllables, not words. "học sinh" (student) is one word of two syllables, and "học" and "sinh" alone mean "study" and "born". `simple` sees two words, so a keyword query for "học sinh" matches any chunk containing "học" or "sinh", because the search matches any query word. Proper handling needs a *word segmenter* (VnCoreNLP, Underthesea) run on both text and query, which is a new dependency in the ingestion worker.
- **Diacritics.** Accents mark tone and vowel quality ("ma", "má", "mả", "mã", "mạ", "mà" are different words). Many people type queries without accents, so "hoc sinh" should match "học sinh"; with `simple` it does not.
- **Stop words.** Very common syllables ("là", "của", "và") are not removed, so they match many chunks and add noise. `ts_rank_cd` weighting reduces the harm but does not remove it.

Why accept it: vector search with bge-m3 is multilingual, understands Vietnamese meaning and is not affected by accents or syllable splitting in this way, and it carries ordinary questions. Keyword search is there for names, numbers and exact phrases, where `simple` is adequate. Whether the gaps hurt on real questions is for the eval set. Fixes in order of cost: an `unaccent` generated column (a migration and a larger index), then a segmenter plus a custom configuration, then a BM25 extension for Postgres, before leaving Postgres.

## Measurements

**Filtering and the HNSW index, for [#63](https://github.com/phuchaitt3/book-rag-app/issues/63), 2026-10-31.** pgvector 0.8.7, PostgreSQL 17, the schema from migration 0001, a throwaway local container. Synthetic data: random 1024-dimension vectors, 1,000 chunks per book, 10 books (10,000 chunks) and then 100 books (100,000 chunks). Real embeddings are clustered by topic and language, so a query's neighbours likely come from its own book; the figures and the size of the filtering effect are unmeasured on real data and could differ in either direction.

- **What the planner does today:** for the app's exact query it ignores the HNSW index and uses the `book_id` index, reads the book's 1,000 rows and sorts them by distance (bitmap scan plus top-N sort). It returned 30 rows, exactly nearest, in about 8 ms with 10 books and about 29 ms with 100 books. The two times are not comparable (the first run's cache state was not recorded, the second was a cold first run, and a repeat took about 4 ms), so no scaling trend can be read from them. A second index starting with `book_id` (the unique constraint on `book_id, ordinal`) could also serve.
- **When only the HNSW index is available** (both `book_id` indexes dropped inside a rolled-back transaction): the planner walks the graph and discards other books' rows. The sample query returned **0 rows**; over 20 random queries on 20 books the average was **0.5 of the 30 rows asked for**. With the default `hnsw.ef_search` of 40, the walk looks at about 40 candidates and almost none belong to the wanted book.
- **With `hnsw.iterative_scan` set to `strict_order` or `relaxed_order`:** every query returned 30 rows.
- **Shows:** no rows are lost today, because the planner picks the exact `book_id` path. **Does not show:** that this holds as the table grows. That a change in size or statistics could flip the planner's choice is an inference, not a measurement. Tables of millions of rows were not measured. The safeguard was implemented in [#84](https://github.com/phuchaitt3/book-rag-app/issues/84).

## At 1000x the load

Roughly 10 million chunks, 40 GB of raw vectors, tens of queries per second. What breaks first, in order:

1. **Memory.** HNSW is fast when the graph fits in RAM. At 40 GB of vectors plus a similar index, a small Neon instance cannot hold it, queries read from disk, and latency jumps from milliseconds to hundreds of milliseconds. Up to about 100x (1 million chunks, 4 GB of vectors) one mid-sized instance is comfortable.
2. **Index build and ingestion.** Building or rebuilding the HNSW index over millions of rows takes hours and a lot of memory, and inserting into a large graph slows down.
3. **Query concurrency.** Search shares CPU and connections with everything else. Connection pooling and a read replica are the first, cheap steps.

Next steps, cheapest first:

- *Partition* the table by book so each query touches one small piece and can use an exact scan. Works while each query touches one book; for a few chosen books it needs the planner to skip the other pieces, which is unverified.
- Store vectors in fewer bytes (`halfvec`, half the memory) or use fewer dimensions.
- Move the vectors to a dedicated store behind `ChunkSearcher`, Postgres staying the source of truth, so the vector store is a derived copy that can be rebuilt. It is *adopted* when a measurement shows the cheaper steps are not enough, and *tried* earlier as an experiment: the same load test and eval set run against both implementations, comparing answer quality, search latency at a given query rate and cost. The thresholds for "not enough" (for example a p95 latency) are not set, because no load test exists yet; setting them is part of that test.

If a feature ever needs search across all books at once ([#89](https://github.com/phuchaitt3/book-rag-app/issues/89)), the per-book trick stops working and the memory problem arrives earlier.

Changing the embedding model is a separate cost: `vector(1024)` ties the table to bge-m3, so a model with a different dimension needs a migration and *every* chunk embedded again, since vectors from different models cannot be compared.

## Read more

- pgvector README, sections on HNSW, IVFFlat and filtering: https://github.com/pgvector/pgvector
- PostgreSQL documentation, chapter "Full Text Search" (tsvector, configurations, GIN, `ts_rank_cd`): https://www.postgresql.org/docs/current/textsearch.html
- Malkov and Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (the HNSW paper): https://arxiv.org/abs/1603.09320
- Cormack, Clarke and Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods" (SIGIR 2009), the paper behind the fusion step.
