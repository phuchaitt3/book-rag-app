# Benchmarks

Measured results for retrieval and answering. Each note links the script that produced it and the command to rerun it.

- [viquad-retrieval.md](viquad-retrieval.md): v1 against v2 retrieval on UIT-ViQuAD2.0, with v1's reworded questions.
- [book-retrieval.md](book-retrieval.md): the same arms on the app's own chunks of one book (Việt Nam sử lược, Quyển I), with generated questions.

## Checklist for a test set

Each item answers a failure seen here or a common one in RAG evaluation (standard: standards/rag-retrieval-eval-without-benchmark, checked 2026-11-09).

1. **No query in what it is searched against.** A query, and the question it was written from, must not be in any index the run searches, unless that variant is labelled as a leaky reference and kept out of comparisons. Each query records its source; the script checks before any model runs and stops on a leak (#175). Why: v1 tested reworded questions against an index that still held their originals, which scored 72% Hit@5 against 24% without them (#173).
2. **No shared generator.** Questions used to test an index built from generated questions come from a different model, or from people.
3. **Questions that do not copy the text.** Include questions written without seeing the passage; questions written while reading it favour keyword search (#173).
4. **Enough questions to separate the designs.** 100 questions give intervals of about ±8–10 points; report 95% bootstrap intervals and paired differences.
5. **Numbers only in the repository.** Dataset text and anything derived from it stay out of git unless the licence allows it.
