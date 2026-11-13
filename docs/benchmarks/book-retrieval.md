# Retrieval on a book: Việt Nam sử lược, Quyển I

Issue #177; rerun 2026-11-10 on the checked question set (#178). Scripts, the question set and rerun steps: [experiments/book-testset/](../../experiments/book-testset/README.md).

**Result.** On the app's own chunks of one history book, the v2 design (bge-m3 + BM25, fused by RRF) puts a gold chunk in the top 5 for **91.8%** of 208 checked questions written from the chunks (95% CI 88.0–95.2). On the same questions rewritten without the chunk in view, it reaches **89.4%** (85.1–93.3). The bge-reranker-v2-m3 cross-encoder over the fused top 20 is the largest single gain: **+21 to +23 points Hit@1** on every set. Fusion's gain over bge-m3 alone on the rewritten set is **+4.8 points Hit@5** (0.0–9.6): smaller than the first run's and at the edge of the interval.

## Setup

- **Corpus:** *Việt Nam sử lược*, Quyển I (Trần Trọng Kim, public domain), from the proofread vi.wikisource transcription. It is chunked by `book_rag.chunking.chunk_book` at the app's defaults (1,200 characters, 150 overlap): 28 sections, 365k characters, **359 chunks**.
- **Questions:** written by `deepseek-v4-pro` with thinking off, from 219 chunks drawn with seed 177 across the chapters, then checked (below).
  - **seen:** the model reads one chunk and writes a question, an answer, and the sentence that answers it. 215 were generated; 4 more were dropped at generation because the sentence was not found in the chunk.
  - **blind:** the same questions, rewritten by the model without the chunk in view.
  - **retrieval needed:** the 120 of 208 questions the model could not answer without the book.
  - **unanswerable:** 25 questions with no gold chunk, counted but not scored here, and not checked.
- **The check** (#178; record in [review.md](../../experiments/book-testset/review.md)): an LLM review (Claude) read all 215 pairs against their evidence and source chunks and flagged 24, and the user then checked every flag and a control sample of 10 unflagged pairs (seed 178). The user confirmed all 24 flags and found all 10 controls sound. 7 pairs were dropped (no answer in the book, figurative answers, duplicates) and 17 fixed (unnamed rulers, rewrites that reversed or changed the question, one answer with a fact from outside its chunk). **208 pairs remain**, committed as [questions.jsonl](../../experiments/book-testset/questions.jsonl).
- **Gold:** the source chunk plus any chunk holding the same evidence sentence (the overlap between chunks), 1.13 chunks per question on average. A hit is any gold chunk in the top k.
- **Leakage guard:** no question, and no blind question's source, appears inside any chunk; there are no near-copies (cosine ≥ 0.95). Questions share 78% (seen) and 67% (blind) of their words with their gold chunk.
- **Intervals:** 95% percentile bootstrap, 2,000 resamples over questions. Differences between arms use paired resamples.
- **Hardware:** GTX 1660 Ti (6 GB), fp32, torch 2.11, Python 3.12. The run took 16 minutes, most of it in the reranker.
- **Cost:** generation took 921 DeepSeek calls and cost at most **$0.65**, counted at peak-hour prices, including two smoke tests. The check made no API calls.

## Results

Hit@k in percent, 95% CI in brackets. 208 questions per set.

| Arm | Design | seen Hit@1 | seen Hit@5 | blind Hit@1 | blind Hit@5 |
|---|---|---|---|---|---|
| 2 | distiluse (v1's model), chunk index | 2.4 (0.5–4.8) | 12.0 (7.7–16.8) | 1.9 (0.5–3.8) | 10.1 (6.3–14.4) |
| 3 | bge-m3, chunk index | 62.5 (56.3–68.8) | 87.5 (83.2–91.8) | 61.1 (54.8–67.3) | 84.6 (79.8–89.4) |
| — | BM25 alone (reference) | 76.4 (70.7–82.2) | 91.8 (88.0–95.2) | 63.0 (56.3–69.7) | 86.1 (81.3–90.9) |
| 4 | v2: bge-m3 + BM25, RRF k=60 | 70.7 (64.9–76.9) | 91.8 (88.0–95.2) | 63.9 (57.7–70.2) | 89.4 (85.1–93.3) |
| 5 | arm 4 + bge-reranker-v2-m3, top 20 | **92.8 (89.4–96.2)** | **99.0 (97.6–100)** | **85.1 (80.3–89.9)** | **95.2 (92.3–98.1)** |

MRR@10: arm 4 0.806 (seen) and 0.754 (blind); arm 5 0.955 and 0.897. Hit@10 and the `*_retrieval_needed` sets are in `results.json`. On the 120 questions that need retrieval, every arm is within 5 points of its full-set figure, so the filter changes no conclusion.

**Paired differences:**

| Comparison | seen Hit@1 | seen Hit@5 | blind Hit@1 | blind Hit@5 |
|---|---|---|---|---|
| Arm 4 − arm 3 (fusion vs bge-m3 alone) | +8.2 (3.4–13.5) | +4.3 (1.0–8.2) | +2.9 (−2.4 to 8.7) | +4.8 (0.0–9.6) |
| Arm 4 − BM25 alone | **−5.8 (−11.5 to 0.0)** | 0.0 (−3.8 to 3.4) | +1.0 (−4.3 to 6.7) | +3.4 (−1.0 to 7.7) |
| Arm 5 − arm 4 (reranker) | **+22.1 (16.8–27.4)** | +7.2 (3.8–10.6) | **+21.2 (15.4–26.9)** | +5.8 (1.9–9.6) |

**What the check changed.** Against the first run on the 215 unchecked pairs (this note's version from #177, in git history), the reranker's gain and the v2 headline figures moved by less than one point. The two smaller effects weakened: fusion's gain over bge-m3 on the blind set fell from +5.6 (0.9–10.2) to +4.8 (0.0–9.6) Hit@5, and BM25's lead over fusion on seen questions fell from 7.9 (2.3–13.5) to 5.8 (0.0–11.5) Hit@1. Both intervals now touch zero.

## What it shows

- **The reranker is the step that matters most,** as on ViQuAD: about +22 points Hit@1 on both sets, and it lifts Hit@5 to 95–99%. It is also most of the cost: about 2 seconds per question on this GPU, which the next retrieval design has to weigh against latency.
- **Fusion may help more on a book than on ViQuAD's reworded questions, but the evidence is thin.** On ViQuAD, fusion's gain over bge-m3 alone disappeared once questions stopped reusing the passage's words (#173). Here it is +4.8 Hit@5 on the blind set, with an interval whose lower end is zero. Questions about a history book carry proper names (rulers, places, dynasties) that the rewrite keeps, and BM25 matches those exactly. A larger set or stronger rewrites (#178) would settle it.
- **On questions that copy the text, RRF may cost BM25 its top rank:** BM25 alone leads fusion by 5.8 points Hit@1 on the seen set, with an interval that reaches zero. At Hit@5 they tie, and on the blind set the gap is gone. An RRF weight that leans toward BM25 (#180), or a reranker after fusion (arm 5), would recover it.
- **v1's embedding model fails on Vietnamese book chunks:** distiluse finds the gold chunk in the top 5 for 12% of questions, against 88% for bge-m3.

## Fusion weight (#180)

Question: should the app's equal-weight RRF lean toward BM25? Score = w/(k+rank_bm25) + (1−w)/(k+rank_dense), k = 60, 30 candidates per list; w = 0.5 is the app's rule. The weights 0.3, 0.4, 0.6, 0.7, 0.8 were fixed before the run; each is compared with w = 0.5 on the same questions (paired, 95% bootstrap intervals), on the 208 checked questions of each kind. Run: `bench.py` on the GTX 1660 Ti, 1,481 s (the reranker's scores are cached across weights). Results: `RESULTS=... python experiments/book-testset/bench.py`; weights through `WEIGHTS`.

Hit@1, difference from w = 0.5 (interval); blind = rewritten questions, the set that decides:

| Set | w | RRF alone | RRF + reranker |
|---|---|---|---|
| blind | 0.3 | −1.4 (−4.8, +1.9) | −1.0 (−2.9, +0.5) |
| blind | 0.4 | −0.5 (−2.4, +1.4) | −1.0 (−2.9, +0.5) |
| blind | 0.6 | +3.4 (0.0, +6.7) | −1.9 (−4.3, 0.0) |
| blind | 0.7 | +2.9 (−1.4, +7.2) | −1.9 (−4.3, 0.0) |
| blind | 0.8 | +2.9 (−1.9, +7.2) | −1.9 (−4.3, 0.0) |
| seen | 0.6 | +4.3 (+0.5, +8.2) | −1.0 (−2.4, 0.0) |
| seen | 0.8 | +5.8 (+1.4, +10.6) | −1.0 (−2.4, 0.0) |

Absolute Hit@1 at w = 0.5 is 63.9% (blind) and 70.7% (seen) for RRF alone, 85.1% and 92.8% with the reranker. BM25 alone: 63.0% and 76.4%.

**What it shows.** Leaning toward BM25 helps RRF alone on copied wording (seen: +4 to +6 points at w ≥ 0.6, intervals above zero), as the issue guessed, and gives no clear gain on rewritten questions (+3 at best, intervals include zero except w = 0.6, whose lower end is 0.0). With the reranker, which the app uses, every other weight is equal or slightly worse than 0.5 (blind Hit@5 −3.4 points at w ≥ 0.6, interval −6.2 to −0.5): the reranker reorders the same top 20, so fusion order matters little, and a BM25-heavy candidate list loses some dense-only hits. The retrieval_needed subsets agree.

**Decision.** Keep equal weights; no ADR or issue for a new weight, because none beats 0.5 on the rewritten set inside the reranked pipeline. Limits: one book, 208 questions per kind (intervals about ±4 points), five fixed weights, k and candidate depth not varied, and the questions were generated, not written by people.

## Limits

- **The rewrites are light.** Blind questions still share 67% of their words with the gold chunk, against 78% for seen ones. The generator ran without thinking to fit a $2 budget, and it kept names and much of the wording. This is a milder test of wording change than ViQuAD's `without_context` set, so BM25's strength here partly reflects the overlap.
- **Synthetic questions.** An LLM wrote every question. A synthetic set ranks retrievers in line with human questions but overstates absolute scores (standard: standards/rag-retrieval-eval-without-benchmark, checked 2026-11-09). Read the comparisons between arms, not the absolute numbers.
- **The check is one pass.** One person checked the 24 flagged pairs and 10 controls; the other 181 pairs had only the LLM review. The control sample found no miss, but 10 pairs bound the miss rate only loosely. 16 blind rewrites written in the check were not generated by the model, and on fixed rows `closed_book_correct` still refers to the original question.
- **The closed-book filter is loose.** Without thinking, the model failed some questions it would know with thinking on, for example the Lê Lai story. So the `*_retrieval_needed` sets keep some questions answerable from general knowledge.
- **One book, 359 chunks.** In a library of many books there are more near-misses per question, and absolute hit rates will fall.
- **Unanswerable questions lack variety and were not checked:** all 25 ask about later archaeology, because the prompt's first example steered them there. They are not used here; a later answer-quality test needs a more varied set.
- **BM25, not Postgres full-text,** as in the ViQuAD note. One run, one seed.
