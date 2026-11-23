# Pre-registration: abstain benchmark on 100+ unanswerable questions (issue #291)

Written and committed before any new question was drafted and before any score was collected. A rule below is not changed after results; a change would be a new, dated section with the reason, and every number it touches is then labelled **exploratory**. Replaces the weakest number in [abstain.md](../../docs/benchmarks/abstain.md) (19 blind unanswerable questions, #222). Question drafting in the style of [#178](../book-testset/PREREG-178.md).

## 1. What is measured, and what is fixed

- **Thresholds are not tuned.** The shipped values stay: `0.2557` on the reranker score (reranker on), `0.0299` on the fused RRF score (reranker off). A question abstains when its top passage's score is under the threshold for its scale. Nothing in this task picks or moves a threshold.
- **Same book, same ingest path, same code** as the #222 run (Việt Nam sử lược, Quyển I; `abstain_scores.py` with `TOP_K=6`; both arms on one ingested book). Any difference in stack (model files, TEI image, commit) is written in the Conditions section of abstain.md.
- **Same intervals:** bootstrap 95%, 10,000 resamples, seed 222. Because a bootstrap of 100% is degenerate (100-100), every rate is also given with the **Wilson 95% interval**, and the Wilson interval is the one the rule in section 4 uses.
- **Answerable side unchanged:** the false-abstain rate comes from the 208 blind answerable questions of `questions.jsonl` (v1), re-scored in the same run, so both numbers come from one stack.

## 2. The new question sets (all written blind)

"Blind" here means: written and reviewed before any score of any new question exists, from chapter titles and the writer's own knowledge, without running the app on them, and never edited after the scores. Writer: Claude (Sonnet 5.5), in the worker's own session.

**Set U, fully unanswerable (`kind: unanswerable`, `split: blind`).**
- Draft 140 (20 in each of 7 patterns), keep those the review accepts. **Final size must be at least 100**; if fewer pass, draft more before any scoring (the number drafted is reported).
- Patterns, each question carries one `category`:
  - `later`: events or research after the book's period (the book stops at the Lê; no archaeology, no modern excavation);
  - `figures`: exact numbers nobody recorded;
  - `abroad`: events outside Vietnam and China;
  - `private`: private life, tastes or thoughts of a person;
  - `present`: present-day places, opening hours, owners, tickets;
  - `near-miss`: shares rare names or keywords with a passage of the book but asks something the book does not state (the hard case for a score-based guard);
  - `false-premise`: asserts a fact the book contradicts or never states ("Why did X do Y in year Z", where it did not).
- **Rules:** every category has at least 12 and at most 25% of the final set; no question mentions `khảo cổ`; none duplicates a question already in `questions.jsonl` or `questions.v2.jsonl`. **Chunk check:** any question whose word overlap with some chunk is at least 0.80 (words as in `testset_v2.py`) is read against that chunk and dropped if the chunk answers it.
- Limit stated in advance: near-miss and false-premise questions are written by a model that does not hold the whole book in view, so some may be answered by a passage nobody read; the review below and the human sample are the guard.

**Set P, partly answered (`kind: partial`), reported on its own.**
- Draft at least 40 and keep at least 30. Each asks two things in one question; one part is answered by a named chunk (`gold_chunks` recorded, the writer reads that chunk first), the other part is not stated anywhere in the book.
- Set P is never pooled with set U and never counted in the headline. Today those questions count as false abstains; here they get their own table. There is no good/bad rule for P: it is reported as a rate with intervals, with the reading "an abstain here is a miss, a pass is a risk of a half-invented answer, neither is right".

## 3. Review (not the writer's own judgment)

- A **different model** (a Claude Opus subagent, which did not write the questions) reads every U and P question with the book text available to it (`data/chunks.jsonl`, searchable) and returns, per question: `unanswerable`, `partial` or `answerable`, with the passage if any. Only questions it labels as drafted (U: `unanswerable`; P: `partial`) are kept; the rest are dropped, not rewritten. The reviewer is told nothing about scores or thresholds.
- This is still a model of the same family and not a person: **until the human sample below is checked, every result in this task is labelled "model-reviewed, human check pending"** and the PR says `Part of #291`, not `Closes`.
- **Human sample (the owner's 10 minutes):** a fixed file of 30 items (21 from U, 3 per pattern, and 9 from P), drawn with `random.Random(291)` from the kept questions before any score exists. Each item shows the question, its label and the closest passage by word overlap; the owner marks "label right / wrong". If the owner marks more than 10% of the sampled U items as answerable, the questions they flag are removed and the tables recomputed with the same thresholds, and the result is reported as recomputed.
- The drafting happens once. Questions dropped by review are listed in the review file; no question is edited or added after the review, and nothing is edited after the scores exist.

## 4. The rule for "good"

For the reranker-on arm, on set U (fully unanswerable, blind):

- **good** iff the Wilson 95% lower bound of the abstain rate is at least **85%**;
- **not good** otherwise. A worse rate than the 19-question run is a valid finish and is reported as it is.

The no-reranker arm is measured and reported with no rule (it is the known weak case). The false-abstain side is reported but not part of the rule, since the answerable questions and the thresholds are unchanged from #222.

Per-pattern rates are reported for U with Wilson intervals; with about 15 to 20 questions per pattern they are descriptive only, and no claim is made about a single pattern from them.

## 5. Out of scope

The issue's step 4 (end-to-end abstention with the real local LLM) is not done: no real-LLM run exists at the time of writing. This task measures the retrieval-stage decision only, as #222 did.
