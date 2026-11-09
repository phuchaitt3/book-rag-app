# UIT-ViQuAD2.0 retrieval benchmark (issue #171)

`viquad_bench.py` compares the v1 retrieval design (distiluse over a question index) with the v2 design (bge-m3 over passages, fused with BM25 by RRF, k=60) and the steps between them. Results: [docs/benchmarks/viquad-retrieval.md](../../docs/benchmarks/viquad-retrieval.md).

It runs as a private Kaggle script kernel on a free T4 GPU with internet on, because it downloads the dataset and three models from Hugging Face. It writes only numbers (`results.json`); no dataset text leaves the kernel, and nothing derived from the dataset is committed (the dataset's licence is not checked).

**Rerun**

```sh
kaggle kernels push -p experiments/viquad-bench
kaggle kernels status <user>/book-rag-viquad-retrieval-bench
kaggle kernels output <user>/book-rag-viquad-retrieval-bench -p <a git-ignored folder>
```

Change `id` in `kernel-metadata.json` to your Kaggle user first. Elsewhere it runs as plain Python with `torch`, `sentence-transformers`, `datasets` and `scipy` installed; set `OUT_DIR` to a writable folder, and `SKIP_RERANK=1` to skip arm 5. It falls back to CPU when no GPU is found (much slower).

**Fixed choices:** train split, answerable rows only, contexts deduplicated by exact text; 1,000 held-out questions drawn with seed 171; 2,000 bootstrap resamples over queries (seed 172). Arm 1 removes all 1,000 held-out questions from its index, as v1 removed its held-out rows.
