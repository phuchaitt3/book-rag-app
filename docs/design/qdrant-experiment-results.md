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
