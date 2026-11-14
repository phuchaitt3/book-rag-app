# LLM-as-judge for answer quality, and the human labels that would validate it (#244)

**Status: the judge is UNVALIDATED.** It runs, it is repeatable, and it is cheap (2.3 s per answer on the local GPU). Whether its scores agree with a person's is not known until the human fills in the labelling sheet and the agreement script is run. Until then no judge score in this repository is evidence of answer quality.

## What was built

- [evals/answer_judge.py](../../evals/answer_judge.py): the judge. A rubric prompt (in Vietnamese) asks for faithfulness to the cited passages, completeness against the reference answer, Vietnamese fluency and an overall `score`, as JSON `{"faithfulness", "completeness", "fluency", "score", "reason"}`, each 1 to 5. Run through the local Ollama model at temperature 0 with a fixed seed and JSON output; no paid API. A reply that is not JSON, or whose `score` is not an integer 1 to 5, is recorded as a parse failure with the raw text and never becomes a score.
- [evals/judge_collect.py](../../evals/judge_collect.py): asks the running app's `POST /books/{id}/chat` for 100 real answers and keeps the passages each answer cites.
- [evals/judge_sheet.py](../../evals/judge_sheet.py): the 40-row labelling sheet for the human, and a separate key file.
- [evals/judge_agreement.py](../../evals/judge_agreement.py): quadratic-weighted Cohen's kappa and Spearman's rho between judge and human, each with a bootstrap 95% interval, plus exact and within-one agreement.
- [evals/judge_report.py](../../evals/judge_report.py): score distribution and a label-free sanity check.
- Tests on a scripted fake judge and on synthetic labels: `apps/api/tests/test_answer_judge.py` (malformed JSON, out-of-range and non-integer scores, backend failure, the sheet hides the system and leaves `score` empty, kappa and Spearman on known values, the script stops on an unfilled sheet).

## What was measured (no human labels involved)

Conditions: the Wikisource PDF of *Việt Nam sử lược*, Quyển I (338 pages, 392 chunks, bge-m3 through Ollama), ingested on a fresh Compose stack; the app's answer model `qwen2.5:3b-instruct`, reranker off, `top_k` 6 or 1; Windows 11 laptop, GTX 1660 Ti 6 GB. Date 2026-11-14. Code: the commit of this pull request. The PDF is the copy fetched on 2026-11-14 for #241 (SHA-256 `3c6aa5b2…ecde12`; a new fetch returned HTTP 500). That is not the hash recorded in [abstain.md](abstain.md) (`e343ad1e…`): the export is regenerated, so the bytes differ, but it parsed to the same 392 chunks.

**The 100 answers.** 100 questions of the [book test set](../../experiments/book-testset/README.md), each used once: 75 answerable (blind split) and 25 unanswerable (the hand-written and generated out-of-scope questions of [abstain.md](abstain.md)), split between two systems, `topk6` (the app's default, 60 answers) and `topk1` (one passage, 40 answers, so often too little to answer from). The system is in the collection file and the key, never in the sheet or the judge's prompt. Of the 100, 14 are the app's "not found" reply (9 on unanswerable questions, 5 false abstains on answerable ones); the reranker was off, so the abstain threshold is the weak fused one ([abstain.md](abstain.md)). 16 unanswerable questions were answered anyway.

**The judge over all 100, two runs each** (raw: [judge-results.json](../../experiments/judge/judge-results.json), [judge-report.json](../../experiments/judge/judge-report.json), answers: [collection.json](../../experiments/judge/collection.json)):

| Item | Value |
|---|---|
| Judge model | `qwen2.5:3b-instruct`, temperature 0, seed 244 |
| Answer model | `qwen2.5:3b-instruct`: **the same model** (self-preference risk, below) |
| Parse failures, run 1 | 2 of 100 (no score; left out below) |
| Score distribution, run 1 (n=98): 1 / 2 / 3 / 4 / 5 | 59 / 1 / 16 / 0 / 22 |
| Same, the 40 sheet rows (all 40 scored): 1 / 2 / 3 / 4 / 5 | 23 / 0 / 7 / 0 / 10 |
| Repeat consistency (same input twice, temperature 0) | identical score on 95.9% of 97 comparable pairs, within one point on 97.9% (3 of 100 pairs had a parse failure in a run) |
| Latency per judged answer | mean 2.29 s, median 2.45 s (200 calls, one at a time) |
| Mean score by outcome | answerable and answered 1.96 (n=68); false abstain 2.60 (n=5); correct abstain on unanswerable **5.00** (n=9); unanswerable but answered anyway **1.75** (n=16) |
| Judge score against token F1 to the reference (answered answerable questions, Spearman) | 0.29 (n=68) |

**What this shows, and does not.**

- The judge is deterministic enough to be usable: re-running the same input gives the same score 96% of the time.
- Its scores are bimodal: 59 ones, 22 fives, one 2 and no 4. A 1-to-5 scale used as a 1-or-5 switch carries little more than a pass/fail, and weighted kappa over such a scale will lean on the two ends.
- It rates every correct abstention 5 and every made-up answer to an unanswerable question near 1, the two cases where the rubric and the reference answer leave little to judge. The case that matters, a partly right answer to an answerable question, is where it is weakest by construction, and the 0.29 correlation with token overlap is low.
- The judge scored `topk6` answers lower (2.10) than `topk1` answers (2.44), although `topk1` has less evidence. That is the opposite of what one expects and is a warning sign about the judge, not a finding about the system; the pools hold different questions, and without human labels there is no way to tell which side is wrong.
- None of this measures agreement with a person.

## Caveats

- **Self-preference.** The judge is `qwen2.5:3b-instruct`, the model that wrote the answers. A model tends to rate its own phrasing higher. The only other pulled model is `bge-m3` (an embedder); the 7B model does not stay loaded next to it on this GPU ([serving-latency.md](serving-latency.md)). A judge from another family would remove this risk; the human labels will show how much it matters here.
- **Position bias.** Each answer is scored on its own (pointwise), so there is no answer order to bias. The order of the passages (rank order, as the app cites them) and the place of the rubric in the prompt still can. Pairwise comparison, where position bias is strongest, is not used. Not measured here.
- **A 3B model as judge is weak**, and the rubric is in Vietnamese, which the model handles worse than English. The rubric was written once and not tuned on these answers or on any label.
- **The reference answer is shown** to the judge and to the human, so completeness has a target. For the unanswerable questions the reference says the book has no answer. A judge without a reference would be harder.
- **The app's "not found" reply is in English** ("This book does not seem to answer that question."), which the fluency criterion would penalise. The human instruction below says to ignore the language of that fixed reply. This is the app's behaviour, not changed here.
- **Which passages are shown.** The sheet and the judge see the passages the answer cites with `[n]` markers; when it cites none, the first two retrieved. An abstention has none.
- One book, one machine, one run per question, 100 answers. The unanswerable questions are few (25), and 15 of the test set's were hand-written by an agent ([abstain.md](abstain.md)).

## What waits for the human

The labelling sheet is [experiments/judge/labelling-sheet.csv](../../experiments/judge/labelling-sheet.csv): 40 rows, shuffled; the `score` column is empty. **The agent that built it did not fill in any label and must not.** The key that says which system wrote each answer ([labelling-key.csv](../../experiments/judge/labelling-key.csv)) is a separate file: do not open it until you have finished.

The 40: 16 `topk6` and 12 `topk1` answers to answerable questions, and 6 + 6 answers of each system to unanswerable questions (5 of those 12 are the app's "not found" reply and 7 are answers; the sheet has no false abstain on an answerable question). The judge has scored all 40 already, so nothing else needs running.

**Steps for the human (about 1 hour 15 minutes: roughly 2 minutes a row; the passages are the slow part).**

1. Open the CSV in a spreadsheet (UTF-8; Excel reads it) or a text editor. Columns: `row_id`, `question`, `reference` (the right answer; "Sách không có câu trả lời..." means the book does not answer), `passages` (what the answer cites), `answer`.
2. For each row write one whole number from 1 to 5 in `score`:
   - 5: correct, complete, supported by the passages, good Vietnamese;
   - 4: correct and supported, with a small gap or an awkward phrase;
   - 3: partly right, or right but not supported by the passages;
   - 2: mostly wrong or off the point;
   - 1: wrong, made up, or no answer when the book has one.
   A "not found" reply is right (5) when the reference says the book has no answer, and wrong (1) when it has one. Ignore the language of that fixed reply. Judge by the reference and the passages, not by how sure the answer sounds. Use `note` for anything odd (optional).
3. Do not open `labelling-key.csv` and do not look at `judge-results.json` while labelling.
4. Save as CSV (UTF-8) over the same file and commit it on a branch (`git add experiments/judge/labelling-sheet.csv`), or hand it to an agent to commit unchanged.
5. Then run (seconds, no model):

   ```sh
   uv run python evals/judge_agreement.py
   ```

   It writes `experiments/judge/agreement.json`: quadratic-weighted kappa, Spearman's rho, exact and within-one agreement, each interval a bootstrap 95% (10,000 resamples of the rows, seed 244). With 40 rows the intervals will be wide; say so when quoting them. Then replace the status line at the top of this note with the numbers and a verdict. A common reading: kappa under 0.4 means do not use the judge; 0.6 and above can support using it for comparing systems, not for absolute scores.

## Reproduce

```sh
uv run python experiments/e2e/fetch_pdf.py        # HTTP 500 on 2026-11-14; any copy of the PDF will do
LLM_MODEL=qwen2.5:3b-instruct docker compose -p judge244 up -d --build db s3 migrate api worker
# upload the PDF (see e2e-real-model.md), wait for the ingestion job to succeed
BOOK_ID=<uuid> python ~/claude-config/scripts/gpu_run.py run --wait -- uv run python evals/judge_collect.py
docker compose -p judge244 down
uv run python evals/judge_sheet.py                # the sheet (score empty) and the key
python ~/claude-config/scripts/gpu_run.py run --wait -- uv run python evals/answer_judge.py
uv run python evals/judge_report.py
```
