# 0005: Build the application first, then improve the RAG logic against an eval set

**Status:** Accepted

**Decided by:** agents (decided before study-design mode; rewritten to the full template on 2026-10-31, the decision itself unchanged)   **Review:** [#38](https://github.com/phuchaitt3/book-rag-app/issues/38), open

## Context

RAG (retrieval-augmented generation) answers a question by first retrieving passages from the book and then asking a language model to answer from them. Its quality depends on many knobs: how the book is cut into chunks, which embedding model is used, how results are ranked and merged, whether a reranker runs, how the question is rewritten, and how the prompt is worded. There are dozens of plausible settings and no way to know by reading about them which are best for *these* books.

The first version of this project (a university project) used techniques that are now two years old, and nothing proved they helped. That is the problem to avoid: an architecture decided by fashion, with no measurement behind it.

An *eval set* (evaluation set) is a list of questions with known right answers, plus a script (the *harness*) that runs the system on them and produces scores. A *golden set* is the hand-checked version of that list. With one, "I think the reranker helps" becomes "recall went from 0.62 to 0.71". Typical measures:
- *context recall*: of the passages needed to answer, how many did retrieval bring back;
- *faithfulness*: does the answer say only what the retrieved passages support;
- *answer correctness*: does the answer match the known right answer.
RAGAS is an open-source library that computes these, partly by asking a language model to act as the judge.

Requirements:
- The project is a portfolio piece, and the README's second priority is "measured, not assumed": answer quality tracked by an eval set in CI.
- One developer, no budget for paid model calls at scale (the repo rules also forbid that without asking).
- The corpus is Vietnamese books; public English benchmarks do not describe it.

Numbers (planned sizes, not built yet):

| | Now | At 1000x |
|---|---|---|
| Golden questions | 30 to 50, written by hand over 2 to 3 books | 5,000 or more, partly generated and hand-sampled |
| Cost of one eval run | no paid calls: fake or cached providers in CI; a local model for real scores | each run calls a judge model thousands of times, so real money and tens of minutes |
| Experiments | one per pull request, a handful per week | many in parallel, needing a tracked history of scores |

## Options considered

**A. Build the whole application on a plain, current baseline first; add a small golden set and harness early; then change one thing per pull request and keep it only if the score improves (chosen).**
- Pros: something works end to end early, so there is a demo and a real thing to measure. The eval is designed against the real system's inputs and outputs, not a guess. Every later improvement is a number, and old techniques (OCR, rerankers) get a fair trial as experiments instead of being assumed in or out.
- Cons: the baseline's first choices (chunk size, prompt) are made without measurement, and they influence what the eval can see. The word "early" is a promise that is easy to postpone; until the harness exists, nothing enforces it.
- Cost: the work of writing the golden set by hand, which is the real cost of this option (about a day for 30 to 50 questions).

**B. Eval first: write the golden set and harness before building the application.**
- Pros: the measuring stick exists before any choice is made, so no choice is ever unmeasured.
- Cons: a harness needs something to run. Its shape (what the system returns, how citations look, which fields exist) is not known until the application exists, so the harness would be redone. Time passes with nothing to demo, and a one-developer project risks stalling before it has any result.

**C. Build the application and tune by feel ("vibes"): try a few questions, keep what looks better.**
- Pros: fastest at the start.
- Cons: not repeatable, easy to fool yourself, and no protection against a change that fixes one question and breaks five. This is how the first version ended up with unproven techniques. It also gives nothing to show a reader, which defeats the portfolio goal.

**D. Reuse the first version's techniques, then evaluate.**
- Pros: less new work.
- Cons: starts from two-year-old choices and a codebase that was not designed to be measured or scaled, and the rebuild exists to leave those behind. The old techniques can still return, as experiments under option A.

**E. Use a public benchmark instead of writing a golden set.**
- Pros: no hand labelling, comparable with published results.
- Cons: public sets use other books and often other languages, so they do not tell whether *this* system finds the right passage in *these* books. A small hand-written set over the real books measures what the user cares about. A public set can be added later as a second signal.

## Decision

Build the whole application end to end on a plain, current RAG baseline first. Add a small golden question set and an evaluation harness early. After that, change the retrieval logic one experiment per pull request (OCR, reranker on or off, chunk size, query rewriting) and keep a change only if the eval improves.

Where this stands on `main`, checked against the code:
- The baseline is built: upload, PDF parsing, section-aware chunking (at most 1,200 characters per chunk, 150 characters of overlap), hybrid retrieval (ADR 0002) and a streamed, cited answer (`packages/rag`, `apps/api`).
- The knobs the decision names are all currently at fixed, unmeasured defaults: the chunk sizes above (`chunk_book` in `packages/rag/src/book_rag/chunking/chunker.py`); no reranker (the API builds `HybridRetriever` without one in `apps/api/src/book_rag_api/main.py`, and no real reranker implementation exists, only a fake one); scanned PDFs without a text layer are rejected (`NoTextError`) because OCR is "a later experiment"; no query rewriting.
- The eval set and harness **do not exist yet**. The README lists them as planned, and [#22](https://github.com/phuchaitt3/book-rag-app/issues/22) tracks the CI eval job. So the "early" in the decision has not happened: the baseline is complete before any measurement.

## Why

**Why build first.** The decision to measure only makes sense once there is something to measure, and a harness written without the real system guesses at its inputs and outputs. Building a plain baseline is cheap, because the choices are well known (hybrid search, chunking by section, a hosted or local model behind an interface). The expensive question, "which of the many knobs help?", is the one the eval answers, and an eval answers it only against a running system.

**Why a small golden set, not a large one.** Thirty to fifty hand-checked questions are enough to see a change of ten points in recall, and cheap enough to write once. A large generated set costs judge-model calls on every run and still needs hand checking, because a model that writes questions and a model that judges answers can share the same blind spots. Growth is left for when the small set stops separating changes.

**Why one experiment per pull request.** If two changes land together and the score moves, nobody knows which one did it. One change per pull request keeps cause and effect attached to a single diff and makes a reverted experiment cheap.

**Why the baseline is chosen "plain".** The baseline should be the least surprising reasonable system, so every experiment is a deviation with a measured effect. The defaults (1,200-character chunks, 30 candidates per search, rank fusion with k = 60) come from common practice and the original papers, not from tuning.

**Assumptions this rests on:** that the golden set can be written by hand in a day or so; that scores from a small set are stable enough to compare (they are noisy, so an improvement under about one question's worth is not a result); and that a CI job can run without paid calls (via fake or cached providers, see ADR 0003).

## Consequences

Easier:
- A demo exists early, and each improvement shows up as a number a reader can check.
- Old techniques can be tried and dropped on evidence, which is the main point of the rebuild.
- Providers sit behind interfaces (ADR 0003), so an experiment that swaps the embedder or reranker is a configuration change.

Harder or committed to:
- **The baseline came first and the harness has not.** Until #22 lands, every default in the list above is unmeasured, and anything built on top of them hardens them. The cost of changing a default grows with what depends on it. The chunk size is the most expensive one: changing it means re-chunking and re-embedding every book (see ADR 0002).
- A golden set must be written and kept. It is data, so it needs the same care as code: it should record which book and page each answer comes from, and it must not leak into the prompt or the indexed text, or the scores become meaningless.
- Scores from a small set are noisy. A change counts only when it beats the noise; the harness should report the spread, not one number.
- An LLM judge (RAGAS) adds its own error and cost. CI therefore needs cached or fake judge outputs, so a run is cheap and repeatable, and real-model scores are produced on demand.
- The decision does not say what happens when two goals conflict (for example higher recall but slower answers). The harness should track latency and cost beside quality, so a trade-off is visible instead of argued from memory.

## At 1000x the load

Here the "load" is the amount of evaluation work, not user traffic: 5,000 or more questions, many books, many experiments at once.

What breaks first, in order:
1. **Cost and time of each run.** Thousands of judge-model calls per run take tens of minutes and real money, and CI stops being a quick check. Next step: run a small fixed subset on every pull request and the full set nightly or on demand; cache the judge's answers by input so unchanged cases cost nothing.
2. **Overfitting to the test set.** Many experiments against one set let a change win by chance or by memorising its quirks. Next step: split the set into one used while experimenting and a held-out one used rarely, and refresh the held-out part from new questions.
3. **Tracking.** A single "baseline" number in the README is not enough once there are many experiments. Next step: store scores per commit (a table or a service such as MLflow or Langfuse) so a regression can be traced to the change that caused it.
4. **Label quality.** Hand-checking thousands of answers does not fit one developer. Next step: sample for review, and measure how often the judge model agrees with a human on that sample.

## Read more

- RAGAS documentation, the metrics section (context recall, faithfulness, answer correctness) and its caveats about LLM judges: https://docs.ragas.io
- Hamel Husain, "Your AI Product Needs Evals": a practical argument for building evals from real examples early.
- Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (2023): how well a model's grading agrees with humans, and its known biases.

## Review

Questions and answers go here, dated, from [#38](https://github.com/phuchaitt3/book-rag-app/issues/38). None yet.
