# Retrieval on a book: Việt Nam sử lược, Quyển I

Issue #177, run 2026-11-10. Scripts and rerun steps: [experiments/book-testset/](../../experiments/book-testset/README.md).

**Result.** On the app's own chunks of one history book, the v2 design (bge-m3 + BM25, fused by RRF) puts a gold chunk in the top 5 for **92.6%** of 215 questions written from the chunks (95% CI 88.8–95.8). On the same questions rewritten without the chunk in view, it reaches **89.3%** (85.1–93.0). The bge-reranker-v2-m3 cross-encoder over the fused top 20 is the largest single gain: **+21 to +24 points Hit@1** on every set. Unlike on ViQuAD's reworded questions (#173), fusion keeps a measurable gain over bge-m3 alone on the rewritten set: **+5.6 points Hit@5** (0.9–10.2).

## Setup

- **Corpus:** *Việt Nam sử lược*, Quyển I (Trần Trọng Kim, public domain), from the proofread vi.wikisource transcription. It is chunked by `book_rag.chunking.chunk_book` at the app's defaults (1,200 characters, 150 overlap): 28 sections, 365k characters, **359 chunks**.
- **Questions:** written by `deepseek-v4-pro` with thinking off, from 219 chunks drawn with seed 177 across the chapters.
  - **seen:** the model reads one chunk and writes a question, an answer, and the sentence that answers it. 215 questions; 4 were dropped because the sentence was not found in the chunk.
  - **blind:** the same 215 questions, rewritten by the model without the chunk in view.
  - **retrieval needed:** the 123 of 215 questions the model could not answer without the book.
  - **unanswerable:** 25 questions with no gold chunk, counted but not scored here.
- **Gold:** the source chunk plus any chunk holding the same evidence sentence (the overlap between chunks), 1.13 chunks per question on average. A hit is any gold chunk in the top k.
- **Leakage guard:** no question, and no blind question's source, appears inside any chunk; there are no near-copies (cosine ≥ 0.95). Questions share 79% (seen) and 66% (blind) of their words with their gold chunk.
- **Intervals:** 95% percentile bootstrap, 2,000 resamples over questions. Differences between arms use paired resamples.
- **Hardware:** GTX 1660 Ti (6 GB), fp32, torch 2.11, Python 3.12. The run took 16 minutes, 93% of it in the reranker.
- **Cost:** generation took 921 DeepSeek calls and cost at most **$0.65**, counted at peak-hour prices, including two smoke tests.

## Results

Hit@k in percent, 95% CI in brackets. 215 questions per set.

| Arm | Design | seen Hit@1 | seen Hit@5 | blind Hit@1 | blind Hit@5 |
|---|---|---|---|---|---|
| 2 | distiluse (v1's model), chunk index | 3.3 (0.9–5.6) | 12.1 (7.9–16.3) | 2.3 (0.5–4.7) | 8.8 (5.6–13.0) |
| 3 | bge-m3, chunk index | 61.9 (54.9–68.4) | 87.0 (82.3–90.7) | 60.0 (53.0–66.5) | 83.7 (78.6–88.4) |
| — | BM25 alone (reference) | 77.7 (72.1–83.3) | 92.1 (88.4–95.3) | 62.3 (55.8–68.8) | 87.0 (82.3–91.2) |
| 4 | v2: bge-m3 + BM25, RRF k=60 | 69.8 (63.7–75.8) | 92.6 (88.8–95.8) | 62.8 (56.3–69.3) | 89.3 (85.1–93.0) |
| 5 | arm 4 + bge-reranker-v2-m3, top 20 | **92.1 (88.4–95.3)** | **98.6 (96.7–100)** | **84.2 (79.1–88.8)** | **94.9 (91.6–97.7)** |

MRR@10: arm 4 0.804 (seen) and 0.746 (blind); arm 5 0.949 and 0.892. Hit@10 and the `*_retrieval_needed` sets are in `results.json`. On the 123 questions that need retrieval, every arm is within 4 points of its full-set figure, so the filter changes no conclusion.

**Paired differences:**

| Comparison | seen Hit@1 | seen Hit@5 | blind Hit@1 | blind Hit@5 |
|---|---|---|---|---|
| Arm 4 − arm 3 (fusion vs bge-m3 alone) | +7.9 (2.8–13.0) | +5.6 (1.9–9.8) | +2.8 (−2.3 to 7.9) | +5.6 (0.9–10.2) |
| Arm 4 − BM25 alone | **−7.9 (−13.5 to −2.3)** | +0.5 (−2.8 to 3.7) | +0.5 (−5.6 to 6.5) | +2.3 (−1.9 to 6.5) |
| Arm 5 − arm 4 (reranker) | **+22.3 (16.7–28.4)** | +6.0 (2.8–9.8) | **+21.4 (15.3–27.4)** | +5.6 (1.9–9.8) |

## What it shows

- **The reranker is the step that matters most,** as on ViQuAD: about +22 points Hit@1 on both sets, and it lifts Hit@5 to 95–99%. It is also most of the cost: about 2 seconds per question on this GPU, which the next retrieval design has to weigh against latency.
- **Fusion helps more on a book than on ViQuAD's reworded questions.** On ViQuAD, fusion's gain over bge-m3 alone disappeared once questions stopped reusing the passage's words (#173). Here it holds at +5.6 Hit@5 on the blind set. Questions about a history book carry proper names (rulers, places, dynasties) that the rewrite keeps, and BM25 matches those exactly.
- **On questions that copy the text, RRF costs BM25 its top rank:** BM25 alone beats fusion by 7.9 points Hit@1 on the seen set. At Hit@5 they tie, and on the blind set the gap is gone. An RRF weight that leans toward BM25, or a reranker after fusion (arm 5), recovers this. The fusion weight is the question this set was built to answer next (#177).
- **v1's embedding model fails on Vietnamese book chunks:** distiluse finds the gold chunk in the top 5 for 12% of questions, against 87% for bge-m3.

## Limits

- **The rewrites are light.** Blind questions still share 66% of their words with the gold chunk, against 79% for seen ones. The generator ran without thinking to fit a $2 budget, and it kept names and much of the wording. This is a milder test of wording change than ViQuAD's `without_context` set, so BM25's strength here partly reflects the overlap.
- **Synthetic questions.** An LLM wrote every question. A synthetic set ranks retrievers in line with human questions but overstates absolute scores (standard: standards/rag-retrieval-eval-without-benchmark, checked 2026-11-09). Read the comparisons between arms, not the absolute numbers.
- **The closed-book filter is loose.** Without thinking, the model failed some questions it would know with thinking on, for example the Lê Lai story. So the `*_retrieval_needed` sets keep some questions answerable from general knowledge.
- **One book, 359 chunks.** In a library of many books there are more near-misses per question, and absolute hit rates will fall.
- **Unanswerable questions lack variety:** all 25 ask about later archaeology, because the prompt's first example steered them there. They are not used here; a later answer-quality test needs a more varied set.
- **A hand check, not a hand-checked set.** One reader checked 20 question pairs: 18 were sound, one was too vague to stand alone, and one answer added a fact from outside the book. The full set has not been checked, so the questions stay out of git for now.
- **BM25, not Postgres full-text,** as in the ViQuAD note. One run, one seed.
