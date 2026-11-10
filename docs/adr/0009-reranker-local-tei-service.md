# 0009: The reranker runs locally as a TEI service; production hosting is decided at deployment

**Status:** Accepted   **Date:** 2026-11-10
**Decided by:** owner (local-only path, 2026-11-10, in [#184](https://github.com/phuchaitt3/book-rag-app/issues/184)); agents (server, image, depth, fallback)   **Confidence:** medium
**Review:** [#186](https://github.com/phuchaitt3/book-rag-app/issues/186), open   **Study note:** [docs/design/0009-reranker-local-tei-service.md](../design/0009-reranker-local-tei-service.md)

## Context

Both retrieval benchmarks rank a cross-encoder reranker as the largest retrieval gain: on the book test set, `bge-reranker-v2-m3` over the fused top 20 adds +22.1 Hit@1 on seen questions and +21.2 on blind ones ([book-retrieval.md](../benchmarks/book-retrieval.md), measured 2026-11-10). The API ran without one: `HybridRetriever` accepted a `Reranker`, but only `FakeReranker` existed ([ADR 0003](0003-model-provider-interfaces.md)).

Forces:

- **The model needs a runtime.** Ollama has no rerank route. Loading the model in the API process means sentence-transformers and torch: a large lockfile change and an API image of several GB.
- **Production cannot self-host it.** ADR 0003: the planned free hosting has too little memory. No hosted demo exists yet.
- **Latency on this laptop** (measured 2026-11-10, method in the study note): on a GTX 1660 Ti, 20 pairs take about 2.6 s at p50 in fp32 and 11 s in fp16. On the CPU image they take about 58 s.
- **A hosted rerank API is a different model** from the one benchmarked, and costs money per call.

## Options considered

- **In-process model** (sentence-transformers and torch in the API). There is no extra service, but the API image grows several GB, a large dependency change is needed, and the API's memory is tied to the model's.
- **Reranker server beside the API** (Hugging Face Text Embeddings Inference, TEI, or Infinity, called over HTTP). The API stays small, and standard-library HTTP needs no new Python dependency. It adds one more service to run.
- **Hosted rerank API** (Cohere, Jina, Voyage). Nothing to run, but it costs money, sends data out, and the model was not benchmarked here.
- **No reranker.** Nothing changes, and the measured gain is lost.

## Decision

The reranker is `BAAI/bge-reranker-v2-m3`, served by TEI (`turing-1.9.4`, fp32) as a local Compose service added by `compose.reranker.yaml`. The API calls it through `TeiReranker` behind the existing `Reranker` protocol (`RERANKER_PROVIDER=tei`), scores the top 20 fused candidates (`RERANK_DEPTH`), and returns the fused order when the reranker fails or takes longer than `RERANK_TIMEOUT` (10 s). Production runs without reranking until hosting is decided at deployment.

## Why

A server keeps the model out of the API's image, lockfile and memory, and the provider stays under 60 lines of standard library, like the Ollama adapters. TEI was the first server tried, and it was kept because it has a pinned, versioned image for this GPU generation and loads this model unchanged (Infinity was not tried): its quality through the app's own retriever matched the benchmark's arm 5 (Hit@1 95.0 on 40 questions, against 92.8 on the full seen set). Depth 20 is what the benchmark measured. The fallback keeps a slow or missing reranker from costing the answer itself (related to [#53](https://github.com/phuchaitt3/book-rag-app/issues/53)).

The reranker sits in an opt-in Compose file, not the base stack, because only the GPU path is fast enough for chat. The base stack keeps working without the 2.2 GB download or a GPU.

The answer would change if hosting with enough memory or a GPU became affordable (self-host the same service there), or if a hosted reranker matches arm 5 on the book test set (switch production to it after that run).

## Consequences

- Locally on a GPU, answers use the design the benchmarks measured best. Retrieval takes about 2.6 s longer per question at p50.
- On a machine without an NVIDIA Turing GPU there is no usable local reranker: the CPU image takes about a minute per question. Another GPU generation needs a different TEI image tag.
- Production differs from local runs until the hosting decision. Production answers are ranked by fusion alone (Hit@1 about 21 points lower on the book set).
- A reranker failure is logged and hidden from the user. A reranker that is always down would show up only in the logs, so no alert exists yet.
- The fp16/fp32 gap and the GPU memory limit (fp32 runs out of memory at warmup above 2,048 batch tokens next to Ollama) are tuned for one 6 GB card. Other hardware needs its own measurement.
- Follow-ups: choose production reranking at deployment (a hosted model must first be rerun as arm 5); the query embedding through Ollama, not the reranker, is most of the remaining retrieval time ([#185](https://github.com/phuchaitt3/book-rag-app/issues/185)).
- Next step as load grows: the reranker is the most expensive step per question, so it scales by depth (fewer pairs), by adding GPU replicas behind one URL, or by caching scores per (question, chunk). The study note covers the trade-offs.

## Change log

- 2026-11-10: accepted with the code in [#184](https://github.com/phuchaitt3/book-rag-app/issues/184). The plan's "CPU image by default" became an opt-in GPU file after the CPU measurement (about 58 s per question).
