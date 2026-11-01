# 0008: Qdrant vector-search experiment

**Status:** Proposed

**Decided by:** agents (exit criteria are defaults taken from the issue's examples; the owner may change them before the first run)   **Review:** [#113](https://github.com/phuchaitt3/book-rag-app/issues/113), open

This ADR does not change [ADR 0002](0002-postgres-pgvector-hybrid-search.md), which stays Accepted. It sets up a bounded, dated experiment to find out whether the vector part of that decision should change. Follows the experiment procedure: criteria first, then code behind the existing interface and a setting, a shadow run, a decision on a fixed date.

## Context

ADR 0002 keeps chunks, vectors and keyword data in one PostgreSQL database with pgvector, and says a dedicated vector store is "not chosen yet, not rejected": the planned scaling step, to be added when a measurement calls for it, and worth trying earlier as an experiment. Today there is no measured problem: about 10,000 chunks, about 40 MB of vectors, a few queries per minute. The experiment is therefore mainly for learning and for a measured comparison, which the project's goals ("measured, not assumed") ask for.

Qdrant is the candidate because it is the cheapest dedicated store to try: one container locally, a free cloud cluster of about 1 GB (claimed in the research of [#90](https://github.com/phuchaitt3/book-rag-app/issues/90), not checked on the vendor page), and `book_id` payload filtering is a core feature. Retrieval already sits behind the `ChunkSearcher` interface (ADR 0003), so the experiment adds an implementation and callers do not change.

## The design under test

- `QdrantChunkSearcher.vector_search` queries Qdrant with a `book_id` filter. `text_search` stays on the Postgres searcher, because keyword search is not part of this experiment.
- A `VECTOR_STORE` setting selects the store: `pgvector` (the default) or `qdrant`. Nothing changes unless it is switched on. There is at most one experimental toggle in this component.
- Postgres stays the source of truth. The Qdrant copy is derived and can be rebuilt from `chunks`.
- Point id = chunk id. Payload holds `book_id`, with a payload index on it (Qdrant's tenant-index option) so filtered search stays fast. Chunk text stays in Postgres; Qdrant stores vectors and ids only.
- The worker upserts to Qdrant after each batch commit. Upserts are idempotent (same id, same vector), so a retried batch is harmless. Deleting a book deletes by `book_id` filter.
- A per-book count check compares the number of points in Qdrant with `chunks.embedding IS NOT NULL` for that book, to detect the two stores drifting apart.
- Locally, Qdrant runs as a service on the Compose network only, because it starts without authentication.
- Shadow mode (a second setting): `vector_search` queries both stores, returns pgvector's result, and logs the overlap at 30 and each store's latency. Errors on the Qdrant path are logged and never shown to the user.

## Exit criteria (fixed before any run)

All measured on real bge-m3 embeddings of at least one real book, with the same questions, the same query rate and the same data for both paths. A number that is estimated and not measured does not count.

| # | Criterion | Pass |
|---|---|---|
| 1 | Recall@30: share of the exact Postgres scan's top 30 that Qdrant also returns (exact scan = `hnsw`/index disabled, sequential order by cosine distance) | mean at least 0.95 over the question set (at least 100 questions) |
| 2 | p95 latency of `vector_search`, measured at the call site including the network hop | Qdrant p95 no worse than pgvector p95 at the same query rate (at least 5 queries per second for 5 minutes) |
| 3 | Memory and cost at today's size | Qdrant container resident memory under 512 MB for the corpus, and no paid plan needed (local container or free cloud tier) |
| 4 | Consistency | per-book count check shows zero drift after a full ingest, a retried batch and a book deletion |

The winner must pass all four. Passing is necessary, not sufficient: the owner still decides whether the extra system is worth it (see the decision below). Criteria 1 to 4 are defaults chosen by the agent that wrote this ADR, taken from the examples in the issue; the owner may change any number before the first measurement. Changing a number after results exist does not count and is recorded here with a dated note.

## Scale-up arm (needs the owner's yes before any spend)

Today's size cannot show where a dedicated store pays off. A second arm would load synthetic vectors at 1 million and 10 million chunks (1024 dimensions) into both stores and repeat criteria 1 and 2 with memory use reported at each size. It may need a larger machine or a paid cloud tier, so it **does not run** until the owner says yes in the review issue, with a spending limit. Without it the experiment can only say how Qdrant compares at today's size.

## Results (measured 2026-11-01)

Run by `scripts/qdrant_experiment.py` on one Windows laptop (Docker Desktop, 7.7 GB for containers, Ollama bge-m3 on the host), Postgres `pgvector/pgvector:pg17` and `qdrant/qdrant:v1.20.0` as in `compose.yaml`. The corpus is one real book: a 71-page Vietnamese PDF, 164 chunks, embedded with bge-m3 (1024 dimensions). The questions are 120 passages (the longest of the first three sentences of a random chunk, seed 0) embedded with the same model. Everything below was **measured**, not estimated, except where it says otherwise. Each path ran alone, one after the other, at 5 queries per second for 300 s (1 book) or 60 s (100 books), 0 errors. Latency is `vector_search` at the call site, so the Qdrant path includes its Postgres fetch of the chunk text (by design, see "The design under test").

| Corpus | Path | p50 ms | p95 ms | p99 ms | recall@30 vs exact scan (mean, min) |
|---|---|---|---|---|---|
| 1 real book, 164 chunks | pgvector | 23.4 | 46.0 | 50.9 | 1.00, 1.00 |
| 1 real book, 164 chunks | Qdrant | 30.8 | 49.6 | 53.2 | 1.00, 1.00 |
| 100 books, 16,400 chunks (99 copies of the book's real embeddings; **synthetic**) | pgvector | 20.6 | 36.3 | 44.9 | 1.00, 1.00 |
| 100 books, 16,400 chunks | Qdrant | 28.8 | 49.5 | 73.6 | 1.00, 1.00 |

A first 100-book run of 60 s gave pgvector p95 278 ms (p99 718 ms) against Qdrant 48 ms. It ran right after a bulk insert, before `ANALYZE` had run, so Postgres planned with stale statistics. After `ANALYZE` the same run gave the 36.3 ms above. The 278 ms figure is an artefact of the test order and is not used. It does show that pgvector's latency after a large load depends on statistics being fresh; Qdrant was not affected.

| # | Criterion | Result | Verdict |
|---|---|---|---|
| 1 | Recall@30 at least 0.95 | 1.00 for both stores, but the test cannot discriminate: each search covers only one book's 164 chunks, small enough that both stores are likely scanning it exhaustively (assumed, not checked inside Qdrant), so a 1.0 says little about approximate-index recall | **Not tested** at this size; needs the scale-up arm |
| 2 | Qdrant p95 no worse than pgvector at 5 qps | Qdrant 49.6 ms against 46.0 ms (1 book); 49.5 ms against 36.3 ms (100 books) | **Not met** (Qdrant is 8% and 36% slower at p95; the extra hop and the Postgres text fetch are part of this) |
| 3 | Qdrant resident memory under 512 MB, no paid plan | 76 MB with 164 vectors, 147 MB with 16,400 vectors; a local container | **Met** |
| 4 | Zero count drift | Postgres 164 and Qdrant 164 after the first ingestion, after a second ingestion that replaced every chunk id, and 0 and 0 after deleting the book from both. Note: nothing in the app deletes a book from Qdrant today (no delete endpoint); the test calls `delete_book` by hand | **Met** for the paths that exist |

Limits of this run, so no one reads more into it than it shows: one book, one machine, 164 chunks per book and 16,400 in total (ADR 0002's "100x" is 1,000,000), the 100-book corpus is the same vectors copied (exact duplicates, which is not how real books behave), the questions are passages from the book and not human questions, and a 60 s run gives few samples at p99. The data that would decide the scale question is the scale-up arm, which has not run.

Reading as of 2026-11-01 (not the decision, which waits for the date above and the owner): at today's size Qdrant is not faster, uses an extra service, and passes only the criteria that cost nothing; the one place it looked better was a measurement artefact. Unless the scale-up arm shows pgvector recall or latency degrading at 1M or more chunks, the expected outcome on 2026-12-15 is **Rejected**.

## Decision date and what happens at it

**Decision date: 2026-12-15.** On that date, whatever has been measured is entered in this ADR and one of these happens:

- **Win** (all four criteria pass and the owner accepts the extra system): a new ADR supersedes the vector part of ADR 0002, the default becomes `qdrant`, and the pgvector vector path, the `VECTOR_STORE` setting and the shadow mode are removed. ADR 0002 is marked **Superseded by** the new ADR for that part.
- **Loss, or no usable result by the date:** this ADR is marked **Rejected** with the numbers, and the Qdrant adapter, the setting, the Compose service and the worker upsert code are deleted. What was learned stays here.

The toggle does not outlive this date. The removal issue is filed in the pull request that adds the setting.

## Consequences

- Tests and the existing Postgres path are untouched while the default stays `pgvector`.
- The experiment adds a dependency (`qdrant-client`), a lockfile change handled as its own task, and a Compose service.
- If it loses, the cost is the time spent and a short-lived second path, both bounded by the date.

## At 1000x the load

This is what the scale-up arm is for. ADR 0002 expects the pgvector index to stop fitting in memory on a small instance somewhere past 100x (about 1 million chunks, 4 GB of vectors). Qdrant offers quantization and sharding for that range; whether they are needed before cheaper Postgres steps (a partial index per book, a bigger instance) is exactly what the 1M and 10M runs would show.

## Read more

- [ADR 0002](0002-postgres-pgvector-hybrid-search.md), option B and "At 1000x the load".
- Qdrant documentation on payload indexes and multitenancy: https://qdrant.tech/documentation/guides/multiple-partitions/
- Fowler, Branch By Abstraction: https://martinfowler.com/bliki/BranchByAbstraction.html

## Review

(The owner's questions and the answers, dated, newest last.)

- 2026-11-01: results added by the agent that ran the measurements (see "Results"). The status stays Proposed until the decision date; no criterion was changed after the results.
