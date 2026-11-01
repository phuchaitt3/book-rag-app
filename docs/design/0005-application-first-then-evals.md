# Study note: application first, then evals

**For:** [ADR 0005](../adr/0005-application-first-then-evals.md)   **Status:** decided in ADR 0005

This note holds the teaching material behind ADR 0005. The ADR states the decision; this note explains the terms, compares the options in depth and works through what breaks at 1000x the load. It was moved out of the ADR on 2026-11-01 (#128); the text is the ADR's earlier wording, lightly trimmed.

## Problem

RAG (retrieval-augmented generation) answers a question by first retrieving passages from the book and then asking a language model to answer from them. Its quality depends on many knobs: how the book is cut into chunks, which embedding model is used, how results are ranked and merged, whether a reranker runs, how the question is rewritten, and how the prompt is worded. There are dozens of plausible settings and no way to know by reading which are best for *these* books.

The first version of this project (a university project) used techniques that are now two years old, and nothing proved they helped. That is the problem to avoid: an architecture decided by fashion, with no measurement behind it.

## Terms

- **Eval set (evaluation set).** A list of questions with known right answers, plus a script (the *harness*) that runs the system on them and produces scores. A *golden set* is the hand-checked version.
- **Context recall.** Of the passages needed to answer, how many did retrieval bring back.
- **Faithfulness.** Does the answer say only what the retrieved passages support.
- **Answer correctness.** Does the answer match the known right answer.
- **RAGAS.** An open-source library that computes these measures, partly by asking a language model to act as the judge.
- **LLM judge.** A model that grades answers. It adds its own error and cost.
- **Held-out set.** A part of the eval set not used while experimenting, so a change cannot win by memorising the set's quirks.

## Requirements

- The project is a portfolio piece, and the README's second priority is "measured, not assumed": answer quality tracked by an eval set in CI.
- One developer, no budget for paid model calls at scale (the repo rules also forbid that without asking).
- The corpus is Vietnamese books; public English benchmarks do not describe it.

Planned sizes (not built yet):

| | Now | At 1000x |
|---|---|---|
| Golden questions | 30 to 50, written by hand over 2 to 3 books | 5,000 or more, partly generated and hand-sampled |
| Cost of one eval run | no paid calls: fake or cached providers in CI; a local model for real scores | each run calls a judge model thousands of times, so real money and tens of minutes |
| Experiments | one per pull request, a handful per week | many in parallel, needing a tracked history of scores |

## Options in depth

**A. Build on a plain baseline, small golden set and harness early, one change per pull request (chosen).**
- Pros: something works end to end early, so there is a demo and a real thing to measure. The eval is designed against the real system's inputs and outputs, not a guess. Every later improvement is a number, and old techniques (OCR, rerankers) get a fair trial as experiments instead of being assumed in or out.
- Cons: the baseline's first choices (chunk size, prompt) are made without measurement, and they influence what the eval can see. "Early" is a promise that is easy to postpone; until the harness exists, nothing enforces it.
- Cost: writing the golden set by hand, about a day for 30 to 50 questions.

**B. Eval first.**
- Pros: the measuring stick exists before any choice is made.
- Cons: a harness needs something to run. Its shape (what the system returns, how citations look, which fields exist) is not known until the application exists, so it would be redone. Time passes with nothing to demo, and a one-developer project risks stalling before it has a result.

**C. Build and tune by feel ("vibes").**
- Pros: fastest at the start.
- Cons: not repeatable, easy to fool yourself, and no protection against a change that fixes one question and breaks five. This is how the first version ended up with unproven techniques. It gives nothing to show a reader, which defeats the portfolio goal.

**D. Reuse the first version's techniques, then evaluate.**
- Pros: less new work.
- Cons: starts from two-year-old choices and a codebase not designed to be measured or scaled. The old techniques can still return as experiments under A.

**E. Use a public benchmark.**
- Pros: no hand labelling, comparable with published results.
- Cons: public sets use other books and often other languages, so they do not tell whether *this* system finds the right passage in *these* books. A public set can be added later as a second signal.

## Where this stands on `main`

Checked against the code on 2026-11-01:

- The baseline is built: upload, PDF parsing, section-aware chunking (at most 1,200 characters per chunk, 150 characters of overlap), hybrid retrieval (ADR 0002) and a streamed, cited answer (`packages/rag`, `apps/api`).
- The knobs are at fixed, unmeasured defaults: the chunk sizes (`chunk_book` in `packages/rag/src/book_rag/chunking/chunker.py`); no reranker (the API builds `HybridRetriever` without one in `apps/api/src/book_rag_api/main.py`, and only a fake one exists); scanned PDFs without a text layer are rejected (`NoTextError`) because OCR is "a later experiment"; no query rewriting.
- The eval set and harness do not exist yet. The README lists them as planned, and [#22](https://github.com/phuchaitt3/book-rag-app/issues/22) tracks the CI eval job. So the "early" in the decision has not happened: the baseline is complete before any measurement.

## Reasoning in depth

- **Why build first.** Measuring only makes sense once there is something to measure. Building a plain baseline is cheap because the choices are well known (hybrid search, chunking by section, a model behind an interface).
- **Why a small golden set.** Thirty to fifty hand-checked questions are enough to see a change of ten points in recall. A large generated set costs judge-model calls on every run and still needs hand checking, because a model that writes questions and a model that judges answers can share the same blind spots. Growth waits until the small set stops separating changes.
- **Why one experiment per pull request.** If two changes land together and the score moves, nobody knows which one did it.
- **Why a plain baseline.** It is the least surprising reasonable system, so every experiment is a deviation with a measured effect. The defaults (1,200-character chunks, 30 candidates per search, rank fusion with k = 60) come from common practice and the original papers, not from tuning.

## Measurements

None. The eval set does not exist yet.

## At 1000x the load

Here the "load" is the amount of evaluation work, not user traffic: 5,000 or more questions, many books, many experiments at once.

What breaks first, in order:
1. **Cost and time of each run.** Thousands of judge-model calls per run take tens of minutes and real money, and CI stops being a quick check. Next step: run a small fixed subset on every pull request and the full set nightly or on demand; cache the judge's answers by input so unchanged cases cost nothing.
2. **Overfitting to the test set.** Many experiments against one set let a change win by chance or by memorising its quirks. Next step: split the set into one used while experimenting and a held-out one used rarely, and refresh the held-out part from new questions.
3. **Tracking.** A single "baseline" number in the README is not enough once there are many experiments. Next step: store scores per commit (a table or a service such as MLflow or Langfuse) so a regression can be traced to the change that caused it.
4. **Label quality.** Hand-checking thousands of answers does not fit one developer. Next step: sample for review, and measure how often the judge model agrees with a human on that sample.

## Read more

- [RAGAS documentation](https://docs.ragas.io): the metrics section (context recall, faithfulness, answer correctness) and its caveats about LLM judges.
- Hamel Husain, "Your AI Product Needs Evals": a practical argument for building evals from real examples early.
- Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (2023): how well a model's grading agrees with humans, and its known biases.
