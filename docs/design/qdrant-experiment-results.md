# Qdrant experiment: measured results

Measurement note for [ADR 0008](../adr/0008-qdrant-vector-search-experiment.md) (issue #115). Method and raw numbers live here; the ADR keeps the exit criteria and a one-line result. The script is `scripts/qdrant_experiment.py` (deleted with the toggle, #120).

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

## Scale-up arm, run locally (2026-11-01): stopped at 500,000 chunks

Approved by the owner as a ramp (200k, 500k, 1M) with memory limits. The data is **synthetic**: each chunk is a real bge-m3 embedding of the 164-chunk book plus random noise (norm about 0.7 against a unit vector), in books of 1,000 chunks. Every query is a noisy copy of a real embedding, aimed at one book, so each search is a `book_id`-filtered search over 1/200 of the collection at 200,000 chunks. Ground truth is an exact within-book scan in numpy over 100 queries. One store ran at a time, each in a container capped at 6 GB, on the 15.9 GB laptop with Docker allowed 7.7 GB. Script: `scripts/qdrant_scale.py`.

| 200,000 chunks (200 books) | Qdrant | pgvector (HNSW, m=16, ef_construction=64) |
|---|---|---|
| Load | 178 s (upsert per book) | 31 s (COPY), then 98 s to build the index |
| Size | not measured | table 1.1 GB, index 1.6 GB |
| Memory | 3.1 GiB right after load, 0.98 GiB after the queries | 2.4 GiB after the build, 2.7 GiB after the queries |
| recall@30 (mean, min) over 100 queries | 1.00, 1.00 | 1.00, 1.00 |
| p50 / p95 / p99 ms, 5 qps for 60 s (301 calls, 0 errors) | 14.4 / 32.8 / 34.1 | 26.2 / 49.9 / 55.3 |

Not comparable like for like: the Qdrant latency is the raw index search (ids only); the pgvector latency is the real `SqlChunkSearcher.vector_search`, which also returns the chunk rows. The Qdrant path in the app adds a Postgres fetch of the text, so its real latency is higher than this table shows. Recall of 1.00 for pgvector probably means the planner scanned the book exactly (an index on `book_id`); this was not checked with `EXPLAIN`.

Findings:
- **Parallel HNSW builds failed in the stock `compose.yaml`:** Postgres asked for a 2 GB shared-memory segment and Docker's default `/dev/shm` is 64 MB (`DiskFullError: could not resize shared memory segment`). It needed `shm_size: 3g` in a local override. The repo's compose file has no `shm_size`, so a production-sized build in that setup fails the same way. Operability issue to track.
- **500,000 chunks: not completed.** The Qdrant load for this step ran for about 12 minutes with no result, then Docker's engine stopped answering (HTTP 500 from the Docker API) and did not come back after restarting Docker Desktop. Free host RAM was 1.4 GB when the step started, below the 1.5 GB stop rule set for the run; the cause of the hang is **not confirmed** (memory pressure on the host is the likely one). Neither the 500k nor the 1M step produced a number, and no pgvector run at 500k happened.
- Peak Qdrant memory at 200k was 3.1 GiB for 0.8 GB of raw vectors, so about 4x raw size during load. If that ratio holds, 500k needs about 8 GB and 1M about 16 GB, more than this laptop has free (extrapolated from one point, not measured).

What this adds: at 200,000 chunks both stores found every true neighbour and stayed under 60 ms at p99. The question the scale-up arm exists to answer, whether pgvector's recall or latency degrades at 1M or more chunks, is **still open**, and on this laptop it cannot be answered. A machine with 32 GB or more, or a short cloud run (needs the owner's yes and a spending limit), is the way to get it.
