# Benchmarks

Measured results for retrieval and answering. Each note links the script that produced it and the command to rerun it.

- [viquad-retrieval.md](viquad-retrieval.md): v1 against v2 retrieval on UIT-ViQuAD2.0, with v1's reworded questions.
- [book-retrieval.md](book-retrieval.md): the same arms on the app's own chunks of one book (Việt Nam sử lược, Quyển I), with generated questions. Includes the fusion-weight test (#180): equal weights stay.
- [e2e-real-model.md](e2e-real-model.md): one real run of the app on a PDF, with and without the reranker, repeated after the BM25 fix (#241: Hit@5 86.5% off, 94.2% on).
- [retrieval-gap.md](retrieval-gap.md): why the app is below the benchmark (the full-text leg).
- [fts-options.md](fts-options.md): ways to fix the full-text leg (#204): BM25 in Postgres matches the benchmark; its latency cost.
- [agent-eval.md](agent-eval.md): a tool-using agent over the MCP tools against single-shot chat on 40 two-part questions (#243): no measurable gain (45.0% against 42.5% both-hit); a larger k does better (65.0%).
- [abstain.md](abstain.md): abstaining on questions the book does not answer (#222): the reranker score at 0.2557 abstains on 100% of 19 blind unanswerable questions at 5.3% false abstains; the fused score is a weak signal.
- [judge.md](judge.md): an LLM-as-judge for answer quality on a local model (#244): repeatable (96% identical scores on rerun) but UNVALIDATED until a human fills in the 40-row labelling sheet.
- [set-local-cost.md](set-local-cost.md): the extra `SET LOCAL` statement in vector search costs one round trip (#93).

## Local Ollama (#304)

Benchmarks #287, #152 and #291 use a local Ollama with `qwen2.5:3b-instruct`, `qwen2.5:0.5b-instruct` and `bge-m3`. No Ollama is installed on the host; use the official image, pinned by digest (Ollama 0.40.17 at the pin), with models in the named volume `ollama-bench-models`. Keep at least 20 GB free on C:.

Start (holds the machine-wide GPU lock until the container stops; run it in the background):

```
python ~/claude-config/scripts/gpu_run.py hold --wait --purpose ollama -- docker run -d --gpus all --name ollama-bench -p 127.0.0.1:11434:11434 -v ollama-bench-models:/root/.ollama ollama/ollama@sha256:ccc42bcd3d5fcf7ab0d532b300382154e1a4da56fc666bdb313b78ebdd912754
```

Pull the models once (they stay in the volume), then check:

```
docker exec ollama-bench ollama pull qwen2.5:3b-instruct
docker exec ollama-bench ollama pull qwen2.5:0.5b-instruct
docker exec ollama-bench ollama pull bge-m3
curl http://localhost:11434/api/tags
```

Stop when no task needs it (never `-v`; the volume keeps the models):

```
docker rm -f ollama-bench
```

## Checklist for a test set

Each item answers a failure seen here or a common one in RAG evaluation (standard: standards/rag-retrieval-eval-without-benchmark, checked 2026-11-09).

1. **No query in what it is searched against.** A query, and the question it was written from, must not be in any index the run searches, unless that variant is labelled as a leaky reference and kept out of comparisons. Each query records its source; the script checks before any model runs and stops on a leak (#175). Why: v1 tested reworded questions against an index that still held their originals, which scored 72% Hit@5 against 24% without them (#173).
2. **No shared generator.** Questions used to test an index built from generated questions come from a different model, or from people.
3. **Questions that do not copy the text.** Include questions written without seeing the passage; questions written while reading it favour keyword search (#173).
4. **Enough questions to separate the designs.** 100 questions give intervals of about ±8–10 points; report 95% bootstrap intervals and paired differences.
5. **Numbers only in the repository.** Dataset text and anything derived from it stay out of git unless the licence allows it.
