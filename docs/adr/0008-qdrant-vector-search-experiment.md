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
