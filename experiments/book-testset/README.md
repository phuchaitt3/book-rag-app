# Book retrieval test set: Việt Nam sử lược, Quyển I (issue #177)

A retrieval test set built from the app's own chunks of one book, so that retrieval designs are chosen on books rather than on short Wikipedia passages (UIT-ViQuAD, [viquad-bench](../viquad-bench/)). It follows the checklist in [docs/benchmarks/README.md](../../docs/benchmarks/README.md).

**The book.** Trần Trọng Kim, *Việt Nam sử lược*, Quyển I (preface, "Nước Việt Nam", Phần I–III, and the appendix), from the proofread transcription on [vi.wikisource](https://vi.wikisource.org/wiki/Vi%E1%BB%87t_Nam_s%E1%BB%AD_l%C6%B0%E1%BB%A3c). The author died in 1953, so the text is in the public domain in Vietnam. The bibliography is left out. The appendix (a transliteration of Han text) is indexed but no questions are drawn from it.

**Steps** (run from the repository root; everything is written to `experiments/book-testset/data/`, which git ignores):

```sh
# 1. Fetch the chapters, build a ParsedBook (one section per chapter, printed page numbers), chunk it
#    with book_rag.chunking.chunk_book at the app's defaults (1,200 characters, 150 overlap).
uv run python experiments/book-testset/fetch_book.py

# 2. Generate questions with the DeepSeek API (needs DEEPSEEK_API_KEY). Smoke test first, then the full set.
uv run --with openai python experiments/book-testset/generate.py --limit 10
uv run --with openai python experiments/book-testset/generate.py --n 220 --unanswerable 25 --budget 5

# 3. Score retrieval. CHECK_ONLY=1 runs only the leakage check; SKIP_RERANK=1 skips arm 5.
#    QUESTIONS picks the question file; the published results use the checked set in git.
QUESTIONS=experiments/book-testset/questions.jsonl uv run --with sentence-transformers --with scipy --with torch \
  --index https://download.pytorch.org/whl/cu128 \
  python experiments/book-testset/bench.py
```

`--with` adds the packages for that run only, so `uv.lock` does not change. The CUDA index gives a GPU build of torch. Do not add `--index-strategy unsafe-best-match`: it picks the newer CPU-only build from PyPI instead (seen 2026-11-10). Without the index, torch runs on the CPU, which is much slower.

**How the questions are made** (`generate.py`; every call is cached in `data/gen/`, so a rerun only pays for what is missing, and each call's tokens and cost go to `data/gen/usage.jsonl`):

- About 220 chunks are drawn with seed 177, spread over the chapters in proportion to their length. Chunks under 300 characters are skipped.
- **seen**: the model reads one chunk and writes a question, a short answer, and the sentence that answers it. A question whose sentence is not found in the chunk is dropped. Its gold chunks are every chunk holding that sentence, because consecutive chunks overlap.
- **blind**: the model sees only the question, not the chunk, and rewrites it in everyday words. This follows #173, where questions written while reading the passage favoured keyword search (checklist item 3).
- **retrieval needed**: the model answers each question without the book, then judges that answer against the reference. Questions it got right are kept, but they are scored separately: the `*_retrieval_needed` sets leave them out (the standard's filter).
- **unanswerable**: 25 questions written from a chapter title alone, asking what the book does not say, plus 15 **hand-written** ones (out-of-period events, other countries, near-misses sharing the book's keywords; `generator: "hand-written"`, #222). They have no gold chunk, carry `answerable: false` and a `split` (seen or blind), and are used for the abstain threshold ([abstain.md](../../docs/benchmarks/abstain.md)), not retrieval.

**Generator.** `deepseek-v4-pro` through DeepSeek's OpenAI-format API (`MODEL` overrides it, for example `deepseek-flash`). It uses JSON mode and retries an empty or invalid reply twice. Thinking is off for every step: with DeepSeek's default (thinking on, high effort), a one-line rewrite used 1,100 output tokens, and the full set would have cost about $1.65 against about $0.55 without thinking. The cost is weaker reasoning. The rewrites stay closer to the original question, and the closed-book check misses some answers the model would know with thinking on, so the `*_retrieval_needed` filter removes fewer questions than it should. Costs are logged at peak-hour prices, so they are an upper bound, and `--budget` caps the total across all runs. No index under test is built by an LLM, and v1's question index used gpt-4o-mini, so the generator differs from every indexing model (checklist item 2).

**Leakage guard** (#175, adapted). The index holds only the book's chunks, so a query can leak only by copying chunk text. Before any model loads, `bench.py` stops if any chunk contains a query's normalised text or its source question's. It also reports near-copies (cosine ≥ 0.95 to a chunk) and the mean share of a query's words found in its gold chunk.

**The checked set** (#178). [questions.jsonl](questions.jsonl) is the generated set after two checks, recorded separately in [review.md](review.md):

1. **LLM review (Claude):** one agent read all 215 seen/blind pairs against their evidence and source chunks, flagged 24 on four criteria (the evidence answers the question; the question stands alone; the answer adds nothing from outside the book; the rewrite keeps the meaning), and drew 10 unflagged pairs with seed 178 as a control sample.
2. **Human check (the user):** confirmed all 24 flags and found all 10 controls sound. 7 pairs were dropped and 17 fixed; changed rows carry `"edited": "#178 review"`.

The result is 208 seen, 208 blind and 25 unanswerable questions. The unanswerable questions were not checked. On fixed rows, `closed_book_correct` is still the verdict for the original question. `data/questions.jsonl` (git-ignored) keeps the raw generated set.

**Licence of the outputs.** The book is in the public domain in Vietnam (the author died in 1953), so the questions, which quote it, are committed.
