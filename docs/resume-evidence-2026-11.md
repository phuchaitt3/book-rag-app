# Evidence report, 2026-11

Per-task record of what was built, where it lives, and what was measured.

**Rule:** a claim counts only if it runs at a commit on `main`. A figure without a commit and the conditions of its run is not evidence; until then the cell reads `TBD`.

| Task | Status |
|---|---|
| Real-model end-to-end ingestion (#189) | Not yet merged; no figures |
| Reranker (#184, PR #188) | Merged; retrieval figures measured, serving latency not yet |
| Serving measurement (#190) | Script and skeleton only; not yet run |

## 1. Real-model end-to-end ingestion (#189)

**Built.** TBD (not yet merged). The report will be `docs/benchmarks/e2e-real-model.md` (to come).

**Commit.** TBD (not yet merged).

**Reproduce.** TBD (not yet merged).

**Figures and conditions.** TBD (not yet run).

## 2. Reranker (#184)

**Built.** A local bge-reranker-v2-m3 cross-encoder served by a TEI container, applied over the fused top 20 retrieval results. Decision: [ADR 0009](adr/0009-reranker-local-tei-service.md). Compose overlay: `compose.reranker.yaml`.

**Commit.** PR #188, merge commit `df0fb2e`.

**Reproduce.**

```sh
pnpm stack:up:rerank
```

The retrieval figures come from the book test set; steps are in [experiments/book-testset/](../experiments/book-testset/README.md).

**Figures and conditions.** From arm 5 of [benchmarks/book-retrieval.md](benchmarks/book-retrieval.md): *Việt Nam sử lược*, Quyển I, 208 checked questions per set, GTX 1660 Ti (6 GB), fp32; 95% CI in brackets.

| Set | Hit@1 | Hit@5 |
|---|---|---|
| seen | 92.8 (89.4–96.2) | 99.0 (97.6–100) |
| blind | 85.1 (80.3–89.9) | 95.2 (92.3–98.1) |

Gain over arm 4 (bge-m3 + BM25, RRF k=60): +22.1 (16.8–27.4) Hit@1 on the seen set and +21.2 (15.4–26.9) on the blind set. The benchmark note puts the reranker's cost at about 2 seconds per question on this GPU. Serving latency with and without it: TBD (not yet run), see task 3.

## 3. Serving measurement (#190)

**Built.** A sequential SSE client, [experiments/serving/measure.py](../experiments/serving/measure.py), that times the first `citations` event, the first `token` event and the `done` event of the chat endpoint over 30 counted questions (3 warm-up), and reports nearest-rank median and p90. Report skeleton: [benchmarks/serving-latency.md](benchmarks/serving-latency.md).

**Commit.** TBD (not yet merged).

**Reproduce.**

```sh
pnpm stack:up            # or pnpm stack:up:rerank
BOOK_ID=<id> LABEL=<label> API_URL=http://localhost:8000 \
  python ~/claude-config/scripts/gpu_run.py run --wait -- \
  uv run python experiments/serving/measure.py
```

**Figures and conditions.** Median and p90 of t_citations, t_first_token and t_total, reranker off and on: TBD (not yet run). Conditions are written by the script into each summary file.
