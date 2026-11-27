# Pre-registration for the multi-chunk question set (issue #183)

Written and committed before any multi-chunk question was drawn, written or scored. A rule below is not changed after results; a change would be a new, dated section with the reason. Scoring code: [multichunk.py](multichunk.py). Questions: written by Claude (Sonnet 5.5) in the worker's own session, not the DeepSeek API (owner decision 2026-11-24, issue #183).

## 1. How the set is generated

- **Spans.** `multichunk.py spans` draws 30 spans with seed 183 from the 359 chunks of `data/chunks.jsonl` (made by `fetch_book.py`): sizes 2, 3 and 4 chunks in the proportion 12 : 12 : 6. All chunks of a span lie in one section (the span may not start in the appendix), each chunk has at least 300 characters, and any two chunks of a span are at least 2 positions apart (so their overlap regions differ and the chunks are distinct pieces of evidence).
- **Writing.** The writer reads the span's chunks and writes one question that **needs every chunk of the span**, an answer, and for each required chunk one **evidence sentence copied verbatim from that chunk** that carries the part of the answer only that chunk gives. A span for which no such question exists is skipped and logged, not replaced by a hand-picked one (the next unused span from the same seeded draw is used, to reach 30 or run out of the 60-span draw).
- **Gold.** One entry per required chunk: the source chunk plus every other chunk that holds the same evidence sentence (the overlap copies). `multichunk.py build` checks each evidence sentence occurs verbatim in its source chunk; a question failing this is dropped.
- **Standing alone.** The question names no chunk, page or "the passage". Same four review criteria as #178: the evidence answers the question; the question stands alone; the answer adds nothing from outside the book; every chunk of the span is needed (checked by the self-review below).
- **Separate set.** Written to `questions.multi.jsonl`, `kind: "multi"`. It never mixes with `questions.jsonl`, so the single-sentence figures stay comparable.

## 2. Metric

- **Recall@k** (k = 5 and 10; k = 5 is the headline): for a question with R required chunks, the share of the R that are **found** in the top k, where a required chunk is found if any of its copies is in the top k. Mean over questions.
- **Hit@k** (k = 1, 5, 10): at least one required chunk found (the single-sentence metric, for comparison).
- **All@5** (secondary): every required chunk found in the top 5.
- Intervals: 95% percentile bootstrap, 2,000 resamples over questions, seed 183. Differences between arms: paired resamples. Reported by span size too (2, 3, 4).
- Recall@k cannot exceed k / R; for R = 4 and k = 5 this is no limit. The note says so.

## 3. Arms

Arms are those of `docs/benchmarks/book-retrieval.md`: 3 (bge-m3, chunk index), 4 (bge-m3 + BM25, RRF k=60), 5 (arm 4 + bge-reranker-v2-m3 top 20), BM25 alone.

- **Run by this worker (no GPU, no model download):** BM25 alone, with the same tokeniser and parameters as `bench.py` (k1 = 1.2, b = 0.75). A uniformly random ranking is the floor. The claim made from this run is limited to BM25 and to how its Recall@5 compares with its Hit@5 on this set and on the single-sentence set (86.1%/91.8% Hit@5, blind/seen).
- **Not run here:** arms 3, 4, 5. They need the bge-m3 model and the reranker on a GPU. `multichunk.py` scores any ranking file (`{id: [chunk ids]}`), and `bench.py` is not changed, so a GPU run only has to write rankings. The issue's second done-when item (how the arms rank) stays open until that run.
- No hypothesis is tested on BM25 alone beyond reporting its numbers with intervals.

## 4. Checks

- **Closed-book filter: not done for this set.** The writer saw the chunks, so it cannot answer closed-book without leakage, and an independent answerer (a second model) is not available to this run. Every question carries `closed_book_correct: null`. A later run must fill it with a model that has not seen the span.
- **Leakage guard:** the same test as `bench.py`: no question's normalised text occurs inside any chunk; word overlap with the gold chunks reported.
- **Self-review (not independent, same model):** a second pass over every question against its evidence, listing each that fails a criterion in section 1; flagged questions are dropped or fixed and listed in `review-183.md`.
- **Human check (not done by the worker):** `review-183.md` lists a sample of about 10 minutes for the owner: every flagged item plus a control sample of 8 unflagged questions drawn with `random.Random(183)`. Until it is done the set is **LLM-reviewed only**.
