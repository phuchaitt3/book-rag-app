# Cost of the `SET LOCAL` round trip in vector search (#93, item 3)

**Result:** the setting adds one statement round trip per vector search: 1 ms median on localhost (3.69 ms against 2.72 ms, 300 runs each, pgvector 0.8 in a container). On a host with network latency L between API and database the cost is about L. At 1 to 2 ms (same region) it is small next to the 2.2 s query embedding (#185) and the reranker. Keep it as it is.

Folding the setting into the query with a CTE around `set_config(..., true)` ran in 2.97 ms median (noise-level against the other arms), and is not recommended: Postgres does not promise that the CTE runs before the index scan reads the setting, so correctness would rest on evaluation order. In this run all three arms returned the full 5 rows, so the check could not show the difference; the seed was too small to force the HNSW-only plan that the regression test builds. The fold is therefore untested for correctness, not shown to be safe.

Limits: one machine, localhost, 405 chunks, fake vectors; no pooler in the path. Rerun on the deployed host before folding anything: `python ~/claude-config/scripts/gpu_run.py run --resource ram --wait -- uv run python experiments/serving/set_local_cost.py`.

Decision: no code change; #93 closes with this note.
