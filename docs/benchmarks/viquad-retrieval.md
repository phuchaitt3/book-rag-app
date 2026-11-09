# Retrieval on UIT-ViQuAD2.0: v1 design against v2 design

Issues #171 and #173, run 2026-11-09. Script and rerun steps: [experiments/viquad-bench/](../../experiments/viquad-bench/README.md).

**Result.** The v2 design (bge-m3 over passages, fused with BM25 by RRF, k=60) puts the right passage in the top 5 for **92.5%** of 1,000 held-out questions (95% CI 90.7–94.1), against **21.0%** (18.6–23.5) for the v1 design (distiluse over a question index). The paired gain is **+71.5 points** (68.6–74.3). Adding the bge-reranker-v2-m3 cross-encoder over the fused top 20 raises Hit@5 to 97.7% and Hit@1 from 75.4% to 89.0%.

## Setup

- Data: `taidng/UIT-ViQuAD2.0` from Hugging Face, train split, answerable rows only: 19,238 questions over 4,101 distinct passages (whole passages, not chunks). Loaded at run time; no dataset text or derived file is in this repository.
- Queries: 1,000 questions drawn at random (seed 171). A hit means the question's own passage is in the top k.
- Intervals: 95% percentile bootstrap, 2,000 resamples over queries; the arm 4 − arm 1 gain uses paired resamples.
- Hardware: Kaggle, one Tesla T4, fp16 for bge-m3 and the reranker; torch 2.11, Python 3.13. Whole run 8.8 minutes.

## Arms and results

| Arm | Design | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---|---|---|---|---|
| 1 | v1: distiluse, question index, held-out questions removed | 12.2 (10.3–14.2) | 21.0 (18.6–23.5) | 26.8 (24.2–29.6) | 0.162 (0.142–0.182) |
| 2 | distiluse, passage index | 7.2 (5.7–8.8) | 14.6 (12.5–16.9) | 19.9 (17.5–22.4) | 0.106 (0.090–0.123) |
| 3 | bge-m3, passage index | 68.4 (65.4–71.2) | 89.2 (87.2–91.2) | 93.5 (91.9–95.0) | 0.772 (0.750–0.793) |
| — | BM25 alone (reference) | 71.8 (69.0–74.5) | 88.5 (86.5–90.4) | 92.6 (90.9–94.1) | 0.791 (0.769–0.811) |
| 4 | v2: bge-m3 + BM25, RRF k=60, 30 candidates each | 75.4 (72.6–78.0) | **92.5 (90.7–94.1)** | 96.7 (95.5–97.8) | 0.830 (0.809–0.849) |
| 5 | arm 4 + bge-reranker-v2-m3 on the top 20 | **89.0 (87.0–91.0)** | 97.7 (96.7–98.6) | 98.5 (97.7–99.2) | 0.929 (0.915–0.942) |

Hit@k in percent, 95% CI in brackets. Paired arm 4 − arm 1: Hit@1 +63.2 (59.9–66.1), Hit@5 +71.5 (68.6–74.3), MRR@10 +0.668 (0.641–0.692).

Time on the T4: arm 1 22 s (encoding 19k questions), arm 2 16 s, arm 3 75 s (encoding 4,101 passages), the BM25 and fusion step under 1 s, arm 5 408 s (20,000 query–passage pairs through the reranker, one query per batch).

## What it shows

- The model, not the index layout, is most of the gain: distiluse is weak on Vietnamese passages (arm 2 is below arm 1, partly because distiluse reads only the first 128 tokens of a passage), while bge-m3 over the same passages reaches 89% Hit@5.
- Fusion helps on top of either path alone: arm 4 beats both bge-m3 alone and BM25 alone on every metric, with non-overlapping Hit@1 intervals against arm 3.
- The reranker is the largest gain at rank 1 (+13.6 points Hit@1) and the largest cost (77% of the run time).

## Reworded questions (#173)

ViQuAD's questions were written by annotators reading the passage, so they share many words with it (above, BM25 alone nearly matches bge-m3). To test retrieval when wording differs, the same arms ran on v1's two sets of 100 questions that gpt-4o-mini rewrote: once with the passage shown (`within_context`), once without (`without_context`, the harder one). Same corpus and models; one run of 9.8 minutes on a T4 also repeated the 1,000-question set, which reproduced the table above.

Arm 1 runs twice here. v1 kept the original questions in its index, so a rewrite can match its own original; with the 100 originals removed, arm 1 is comparable to the other arms.

| Arm | within: Hit@1 | within: Hit@5 | without: Hit@1 | without: Hit@5 |
|---|---|---|---|---|
| 1 v1, originals kept (as v1 ran it) | 52 (42–62) | 67 (57–76) | 58 (48–68) | 72 (63–81) |
| 1 v1, originals removed | 19 (12–27) | 32 (23–42) | 14 (8–21) | 24 (16–33) |
| 2 distiluse, passages | 14 (7–21) | 26 (18–35) | 12 (6–19) | 22 (14–30) |
| 3 bge-m3, passages | 76 (68–84) | 96 (92–99) | 63 (54–72) | **90 (84–95)** |
| — BM25 alone | 72 (63–81) | 89 (83–95) | 50 (40–60) | 73 (64–82) |
| 4 bge-m3 + BM25, RRF | 78 (70–86) | 97 (93–100) | 63 (54–72) | 88 (81–94) |
| 5 arm 4 + reranker, top 20 | **91 (85–96)** | **100 (100–100)** | **75 (66–83)** | **94 (89–98)** |

100 questions per set, so intervals are about ±8–10 points. Paired differences (Hit@5 unless stated):

- Arm 4 − arm 3 (does fusion beat bge-m3 alone?): +3.3 (1.5–5.1) on the 1,000 dataset questions, +1 (−4 to +6) within context, **−2 (−9 to +5) without context**.
- Arm 4 − BM25 alone: +8 (3–13) within, +15 (8–22) without.
- Arm 5 − arm 4, Hit@1: +13 (4–22) within, +12 (4–20) without.
- Arm 4 − arm 1 as v1 ran it: +30 (21–40) within, +16 (6–26) without.

**What it shows**

- When questions stop reusing the passage's words, BM25 falls from 88.5% to 73% Hit@5 and **fusion's gain over bge-m3 alone disappears**: no measurable gain either way at this size. Fusion's +3 points on the dataset questions most likely came from that word overlap. It still does no measurable harm, and full-text search keeps its usual uses (exact names, rare terms), which these sets do not test.
- **The reranker is the step that holds up**: about +12 points Hit@1 on both reworded sets, as on the dataset questions.
- v1's design looks far better with the original questions left in its index (72% against 24% without context): matching a rewrite to its own original is the leak, not retrieval. v1's own reported figures on these sets carry that advantage.

## Limits

- **Lexical overlap favours BM25** (measured in the section above). ViQuAD annotators wrote questions while reading the passage, so questions share many words with it; BM25 alone does nearly as well as bge-m3 here. Questions from real readers of a book overlap less, so the BM25 share of the gain is likely smaller in the app.
- **Small corpus.** 4,101 passages is far smaller than a library of books split into chunks; absolute hit rates will fall as the corpus grows. The comparison between arms is the result, not the absolute numbers.
- **Not v1's exact number.** v1 reported 37% on its own 100-query set; this run uses 1,000 random questions and finds 26.8% at k=10 for the same design. The sets and scoring differ, so the two are not directly comparable.
- **BM25, not Postgres full-text.** v2's text path is Postgres `to_tsvector('simple', …)` ranking; this run uses BM25 (k1=1.2, b=0.75) over the same lowercase word tokens. The ranking functions differ.
- One run, one seed, one split. The intervals cover query sampling, not model or seed variation.
