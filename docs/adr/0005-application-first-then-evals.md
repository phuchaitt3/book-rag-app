# 0005: Build the application first, then improve the RAG logic against an eval set

**Status:** Accepted   **Date:** 2026-10-30
**Decided by:** agents (before study-design mode)   **Confidence:** medium
**Review:** [#38](https://github.com/phuchaitt3/book-rag-app/issues/38), open   **Study note:** [docs/design/0005-application-first-then-evals.md](../design/0005-application-first-then-evals.md)

## Context

RAG (retrieval-augmented generation) retrieves passages from the book and asks a language model to answer from them. Its quality depends on many knobs: chunking, embedding model, ranking and merging, reranker, question rewriting, prompt wording. Reading about them does not say which are best for these books. The first version of this project used techniques that are now two years old, and nothing proved they helped; this rebuild must not decide by fashion.

An eval set is a list of questions with known right answers plus a script (the harness) that scores the system on them, so "the reranker helps" becomes "recall went from 0.62 to 0.71".

Requirements: the project is a portfolio piece and the README's second priority is "measured, not assumed"; one developer with no budget for paid model calls at scale; the corpus is Vietnamese books, which public English benchmarks do not describe. Planned sizes (not built yet): 30 to 50 hand-written golden questions over 2 to 3 books, no paid calls in CI, about one experiment per pull request.

## Options considered

- **A. Build the application on a plain, current baseline; add a small golden set and harness early; then change one thing per pull request and keep it only if the score improves.** Something works end to end early, and the eval fits the real system. The first choices (chunk size, prompt) are unmeasured, and "early" is easy to postpone.
- **B. Eval first, before the application.** No choice is ever unmeasured. The harness needs a running system to fit, so it would be redone, and nothing can be demoed meanwhile.
- **C. Build and tune by feel.** Fastest start. Not repeatable, and how the first version ended up with unproven techniques.
- **D. Reuse the first version's techniques, then evaluate.** Less new work, but it starts from two-year-old choices the rebuild exists to leave. They can return as experiments under A.
- **E. A public benchmark instead of a golden set.** No hand labelling. Other books and languages, so it does not measure these books. It can be added later as a second signal.

The full comparison is in the study note.

## Decision

Build the whole application end to end on a plain, current RAG baseline first. Add a small golden question set and an evaluation harness early. After that, change the retrieval logic one experiment per pull request (OCR, reranker on or off, chunk size, query rewriting) and keep a change only if the eval improves.

On `main` today the baseline is built (upload, PDF parsing, section-aware chunking of at most 1,200 characters with 150 overlap, hybrid retrieval, a streamed cited answer). Every knob is at an unmeasured default: no reranker, no OCR (scanned PDFs are rejected), no query rewriting. The eval set and harness do not exist yet; [#22](https://github.com/phuchaitt3/book-rag-app/issues/22) tracks the CI eval job.

## Why

A harness written without the running system guesses at its inputs and outputs, and the baseline is cheap because its choices are well known. The expensive question, which knobs help, is answered only by an eval against a running system.

A small golden set (30 to 50 questions) is enough to see a ten-point change in recall and cheap to write once. A large generated set costs judge-model calls on every run and still needs hand checking, because a model that writes questions and one that judges answers can share blind spots. One experiment per pull request keeps cause and effect attached to a single diff and makes a reverted experiment cheap. The baseline is deliberately plain (1,200-character chunks, 30 candidates, rank fusion with k = 60, from common practice), so every experiment is a measured deviation.

The decision rests on these assumptions: the golden set can be written by hand in about a day; scores from a small set are stable enough to compare (they are noisy, so a gain under about one question is not a result); a CI job can run without paid calls through fake or cached providers (ADR 0003). It would change if the small set stops separating changes, or if the harness cannot be built without a paid judge.

## Consequences

- A demo exists early and each improvement is a number a reader can check; old techniques are tried and dropped on evidence; swapping the embedder or reranker is a configuration change (ADR 0003).
- The baseline came first and the harness has not, so every default is unmeasured until #22 lands, and anything built on them hardens them. Chunk size is the most expensive to change: it means re-chunking and re-embedding every book.
- The golden set is data: it records the book and page behind each answer and must not leak into the prompt or the indexed text. Scores are noisy, so the harness should report the spread, and track latency and cost beside quality so a trade-off is visible.
- An LLM judge (RAGAS) adds error and cost, so CI needs cached or fake judge outputs and real scores are produced on demand.
- Next steps as eval work grows, in order: a small fixed subset per pull request and the full set nightly, with cached judge answers; a held-out split against overfitting; scores stored per commit (MLflow or Langfuse); sampled human review of labels. The analysis is in the study note.

## Change log

- 2026-10-31: rewritten to the full template with options, consequences and the 1000x analysis ([#38](https://github.com/phuchaitt3/book-rag-app/issues/38)).
- 2026-11-01: rewritten to the short template; terms, options in depth and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
