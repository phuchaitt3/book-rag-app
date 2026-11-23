# Pre-registration for the book test set v2 (issue #178)

Written and committed before any v2 question was generated or graded. A rule below is not changed after results; a change would be a new, dated section with the reason. Script: [testset_v2.py](testset_v2.py). Generator and answerer: Claude (Sonnet 5.5), in the worker's own session, not the DeepSeek API (owner decision 2026-11-24).

**Baseline (v1, computed 2026-11-24 before the rules below).** Word overlap with the source chunk (the share of a query's distinct words, as `bench.py` tokenises them, that appear in the chunk): seen 0.784, blind 0.668; 5.3% of seen and 15.9% of blind questions are at or under 0.50.

## 1. Stronger blind rewrites

- Input to the rewriter: the seen question only (no chunk, no answer, no evidence), as in v1. Instruction: keep the meaning and the kind of answer asked for; use everyday words; do not reuse the book's rare words where a plain synonym or a description exists; names and dates the question needs stay.
- **Metric:** word overlap of the rewrite with the source chunk.
- **Keep rule:** a rewrite is kept as `blind` in v2 iff overlap <= 0.50. One retry per question (a second rewrite, told to avoid the words of the first); a pair still above 0.50 after the retry keeps no v2 blind question (its seen question stays).
- **Success:** mean overlap of the kept rewrites <= 0.55, and at least 50% of the 208 pairs have a kept rewrite. If not met, the PR says so and v2 blind questions are reported as a partial set; the threshold stays.
- **Meaning check:** an LLM self-review by the same model (Claude), so it is not independent; it lists every pair whose rewrite changes the question. The human check below is the real one.

## 2. Closed-book filter

- Answerer: Claude (Sonnet 5.5), seen question only, no answers shown, in one pass. It knows more of Vietnamese history than the model used in v1, so it is expected to mark more questions closed-book answerable; the `*_retrieval_needed` sets will be smaller. This is a property of the new filter, not an error.
- **Grader: deterministic, no LLM judge**, so the answering model never grades itself: an answer is correct iff at least 60% of the distinct words of the reference answer appear in it (words as in `testset_v2.py`: NFC, lowercase, hyphens as spaces). No manual override. A lexical grader undercounts paraphrases, so it keeps some questions the model does know; stated as a limit.
- Pairs c0, c2, c6 (answers seen by the worker before this was written) keep their v1 verdict.
- `closed_book_correct` of a pair is the verdict for its seen question (as in v1).

## 3. Varied unanswerable questions

- 25 new questions, written from chapter titles only (no chunk text), replacing the 25 generated ones; the 15 hand-written stay.
- Categories (each question carries one): `later` (events or research after the book's period, but not archaeology), `figures` (exact numbers nobody recorded), `abroad` (events outside Vietnam and China), `private` (private life, thoughts, daily detail of a person), `false-premise` (a near-miss sharing the book's keywords but asking about something the book does not state), `present` (present-day places or people).
- **Rules:** at least 5 categories used; no category above 30% (at most 7 of 25); no question mentions archaeology (`khảo cổ`); none duplicates a hand-written question. A question whose overlap with some chunk is >= 0.80 is read against that chunk and dropped if the chunk answers it; the dropped one is replaced and the replacement is checked the same way.
- The 25 are not checked by a person; as in v1 they are used for the abstain threshold only.

## 4. Human check (not done by the worker)

- Held-out control sample: `random.Random(178).sample(sorted(seen ids), 10)` (printed by `testset_v2.py control`). The worker does not edit these pairs after the review pass; they go to the human as unflagged controls beside every pair the self-review flags.
- Until the user has checked, the v2 file is **LLM-reviewed only** and is not the set `bench.py` uses by default; `questions.jsonl` (v1) stays the published set.
