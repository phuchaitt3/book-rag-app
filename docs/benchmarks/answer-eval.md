# Answer-quality eval without a judge model (#221)

A harness that scores the chat endpoint's answers with deterministic metrics, so no judge model or paid API is needed. It unblocks the CI eval job (#22), which was skipped because RAGAS needs a judge.

**Result.** The harness runs in pytest with the fake providers in about 35 s (most of it the Postgres container start). A local run with a real chat model was **not done**: Ollama on this machine held only `bge-m3` (no chat model) on 2026-11-14 and no model was pulled. So no answer-quality number for a real model exists yet.

## Metrics

[evals/answer_eval.py](../../evals/answer_eval.py) posts each question to `POST /books/{id}/chat`, parses the event stream, and scores:

| Metric | Definition |
|---|---|
| Citation hit | A returned citation's chunk contains the question's `evidence` sentence. Same matching as [retrieval_check.py](../../experiments/e2e/retrieval_check.py) (its `norm` is imported): lowercase letters only, no digits, punctuation or Han characters. Questions with no evidence (unanswerable) are not scored. |
| Cited-answer hit | The same, but only chunks the answer cites with a `[n]` marker. Lower than citation hit when the answer cites the wrong passage or none. |
| Citation validity | Every `[n]` marker in the answer is between 1 and the number of citations. An answer with no marker is valid; it is counted in "answers with no marker" instead. |
| Token F1, reference recall | Word-token overlap (NFC, lowercase, markers removed, repeats counted) between the answer and the reference `answer`. Only questions that have one. Containment-style recall is the share of reference words found in the answer. |
| Format errors | Status not 200, a malformed event block, first event not `citations`, no single final `done`, unexpected event names, an empty answer, or a transport failure. |
| Stream errors | The stream carried an `error` event (model failed or timed out part-way). Counted separately from format errors. |

Token overlap rewards the right words, not the right meaning, and punishes long answers; treat it as a regression signal, not a quality score. A judge model would add faithfulness, which is not measured here.

## Fake-provider run (plumbing check, not quality)

[test_answer_eval.py](../../apps/api/tests/test_answer_eval.py) seeds the 8-chunk excerpt in [evals/fixtures/mini-book.json](../../evals/fixtures/mini-book.json) (6 blind questions of the checked set plus 1 unanswerable; text is public domain), uses `FakeEmbedder`, and a scripted LLM that answers with the reference plus `[1]`, except one invalid marker `[9]`, one answer with no marker and one mid-stream failure. Retrieval `top_k` is 3. The metrics it produces are therefore set by the script, except the hits, which come from the fake retrieval:

| Metric | Value |
|---|---|
| Questions | 7 |
| Format errors / stream errors | 0 / 1 |
| Citation hit (n=6) | 100.0% |
| Cited-answer hit | 50.0% |
| Citation validity | 85.7% |
| Answers with no marker | 28.6% |
| Token F1, mean (n=6) | 0.8333 |

## Run it

```sh
# Fake providers, in CI and locally (needs Docker for Postgres, like the other chat tests)
uv run pytest apps/api/tests/test_answer_eval.py

# Live: the stack running with a chat model, a book ingested, BOOK_ID its id
BOOK_ID=<uuid> LABEL=ollama uv run python evals/answer_eval.py
```

Environment variables are listed in the script's docstring (`KINDS`, `TOP_K`, `LIMIT`, `OUT_DIR`, ...). A live run writes `evals/results/answer-eval-<label>.json` (summary and per-question rows) and `.md` (summary table). The set's gold chunk numbers belong to the HTML chunking, so evidence-sentence matching is used, as in the e2e note ([e2e-real-model.md](e2e-real-model.md)). The live run reads chunk text from Postgres.

## Left for #22

A judge model for faithfulness and relevance; a baseline file and a regression gate in CI; a recorded run with a real local chat model.
