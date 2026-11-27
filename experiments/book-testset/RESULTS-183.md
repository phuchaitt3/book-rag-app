# Results for the multi-chunk question set (issue #183)

Rules: [PREREG-183.md](PREREG-183.md). Questions: [questions.multi.jsonl](questions.multi.jsonl), written by Claude (Sonnet 5.5) in the worker's session. Scoring: `multichunk.py score`, 2,000 paired bootstrap resamples, seed 183. Run on a CPU, 2026-11-24; BM25 only.

**What was done.** 30 questions from spans of 2 chunks (12 questions), 3 chunks (14) and 4 chunks (4). That is 11% of the 268 scored questions of the checked single-sentence set and this one together , so the set is small. Gold is one group per required chunk: 1.12 chunks per group on average (the source chunk plus its overlap copies).

**Deviations from the pre-registration.** Spans 0 and 17 were skipped, with no question written: span 0 holds a family-tree table (chunk 268) and span 17 the verse of the Bình Ngô đại-cáo (chunk 308); the next spans of the seeded draw were used instead, as the pre-registration says. Spans 32 and 33 were read but not used because 30 questions had been reached. The closed-book filter was not done (pre-registered as not done). The scoring comparison across arms was not done (see "Not done").

## BM25 alone, 30 questions, 95% CI

| Metric | BM25 alone | Random ranking |
|---|---|---|
| Recall@1 | 33.3 (27.2-38.9) | 3.9 (0.0-8.3) |
| Recall@5 (headline) | **68.9 (58.9-78.6)** | 5.6 (1.1-11.1) |
| Recall@10 | 84.4 (76.1-91.7) | 8.3 (2.8-14.4) |
| Hit@1 | 83.3 (70.0-93.3) | 10.0 (0.0-20.0) |
| Hit@5 | 96.7 (90.0-100) | 13.3 (3.3-26.7) |
| All@5 (every required chunk in the top 5) | 36.7 (20.0-53.3) | 0.0 |
| All@10 | 63.3 (46.7-80.0) | 0.0 |

Recall@5 by number of required chunks (point estimates; 12, 14 and 4 questions): 2 chunks 83.3, 3 chunks 61.9, 4 chunks 50.0. BM25 minus random, Recall@5: +63.3 (53.1 to 73.6).

## What it shows (and does not)

- **Hit@5 hides most of the gap.** BM25 finds at least one required chunk for 96.7% of the questions, but all required chunks in the top 5 for only 36.7%, and on average 68.9% of the required chunks. On the single-sentence set the same retriever's Hit@5 is 91.8% (seen) and 86.1% (blind) (book-retrieval.md); the multi-chunk Hit@5 is not lower, because a question that names several things gives BM25 more words to match. Recall@5, the measure the issue asked for, is 28 points lower than Hit@5.
- **More required chunks, lower Recall@5** (83 → 62 → 50 points), as expected, but the 4-chunk group has 4 questions and its interval is not usable.
- **The questions copy the book's words.** Mean word overlap of a question with the chunks of its span is 0.90, above the single-sentence set's seen questions (0.78) and well above its blind ones (0.67). They were written with the chunks in view and joined several facts into one sentence, so they favour keyword search. A lexical arm is flattered; the dense arms, which this set is meant to separate, are not measured here.
- **Facts are bundled, not reasoned over.** Within a span the facts come from one chapter but are mostly unrelated to each other (a date, a place name, a number); few questions need the chunks to be *combined* (compare, follow a cause). The set tests gathering, not synthesis. A later set should draw spans that share a topic.

## Not done

- **Arms 3, 4, 5** (bge-m3, bge-m3 + BM25 with RRF, plus the reranker) need the embedding and reranker models on a GPU; this machine has a GTX 1060 and no room for the models. The issue's done-when item "says how the arms rank compared with the single-sentence set" is **open**. To finish it, `bench.py` has to write each arm's top-10 chunk ids per question to a JSON file (`{id: [chunk ids]}`) for `questions.multi.jsonl`; `multichunk.py score FILE` then scores it.
- **Closed-book filter**, human check of the flags and the control sample ([review-183.md](review-183.md)), and the leakage guard against the dense arms. The leakage guard that needs no model ran: no question is contained in a chunk.
- **Limits.** 30 questions, one book, one writer that is also the self-reviewer, BM25 only; intervals are wide (±10 points).
