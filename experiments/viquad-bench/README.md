# UIT-ViQuAD2.0 retrieval benchmark (issues #171, #173, #175)

`viquad_bench.py` compares the v1 retrieval design (distiluse over a question index) with the v2 design (bge-m3 over passages, fused with BM25 by RRF, k=60) and the steps between them. Results: [docs/benchmarks/viquad-retrieval.md](../../docs/benchmarks/viquad-retrieval.md).

It runs as a private Kaggle script kernel on a free T4 GPU with internet on, because it downloads the dataset and three models from Hugging Face. It writes only numbers (`results.json`); no dataset text leaves the kernel, and nothing derived from the dataset is committed (the dataset's licence is not checked).

**Rerun**

```sh
kaggle kernels push -p experiments/viquad-bench
kaggle kernels status <user>/book-rag-viquad-retrieval-bench
kaggle kernels output <user>/book-rag-viquad-retrieval-bench -p <a git-ignored folder>
```

Replace `<your-kaggle-user>` in the `id` of `kernel-metadata.json` with your Kaggle user first. Elsewhere it runs as plain Python with `torch`, `sentence-transformers`, `datasets`, `scipy`, `pandas` and `openpyxl` installed; set `OUT_DIR` to a writable folder, and `SKIP_RERANK=1` to skip arm 5. It falls back to CPU when no GPU is found (much slower).

**Fixed choices:** train split, answerable rows only, contexts deduplicated by exact text; 1,000 held-out questions drawn with seed 171; 2,000 bootstrap resamples over queries (seed 172). Arm 1 removes all 1,000 held-out questions from its index, as v1 removed its held-out rows.

**Query sets:** the 1,000 held-out dataset questions (#171), and v1's two sets of 100 questions that gpt-4o-mini rewrote with and without the passage shown (#173). The script reads those from the public v1 repository (`phuchaitt3/book-rag`, `Source_Code/Evaluation/`) at run time. On the rewritten sets arm 1 runs twice: with the original questions left in its index, as v1 ran it, and with them removed.

**Leakage guard (#175):** every query records the dataset question it came from. Before any model runs, the script checks each arm-1 index for those source questions and for the query's own text, and stops if it finds either in a variant not marked as a leaky reference; it also reports near-copies (cosine ≥ 0.95). `CHECK_ONLY=1` runs only the data loading and this check, on CPU, in under a minute. The rule behind it is in [docs/benchmarks/README.md](../../docs/benchmarks/README.md).
