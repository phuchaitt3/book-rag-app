# 0003: Every model sits behind a provider interface

**Status:** Accepted   **Date:** 2026-10-30
**Decided by:** agents (before study-design mode)   **Confidence:** high
**Review:** [#36](https://github.com/phuchaitt3/book-rag-app/issues/36), open   **Study note:** [docs/design/0003-model-provider-interfaces.md](../design/0003-model-provider-interfaces.md)

## Context

The app calls three kinds of model: an embedder (text to a 1024-number vector), a reranker (scores a passage against a question) and an LLM (writes the answer, streamed). Each can run on the developer's machine (Ollama) or on a vendor's servers (hosted, paid per use).

Constraints: local development needs no vendor account or bill; the self-hosted models need several GB of RAM, far more than a free hosting plan offers, so production cannot self-host them; tests and load tests must be fast, deterministic and free, and a load test must measure our code, not a vendor's latency; answer quality must be comparable across models (ADR 0005). The model sizes are taken from the Ollama model pages; the traffic figures are estimates.

## Options considered

- **A. Call the model library directly where needed.** Least code today. Every caller knows one vendor's format, tests need the real service or a mock of its HTTP calls, and switching vendors means editing every caller.
- **B. One interface per kind of model, with swappable implementations.** Tests use a fake, local and production differ only in configuration, a new vendor is one class. The contract is a guess about what implementations share and can leak.
- **C. A third-party abstraction layer** (LiteLLM, LangChain). Many vendors out of the box. A large dependency and a lockfile change, and our own interfaces (dimension-reporting embedder, reranker, fakes) would still be needed on top.
- **D. One hosted vendor for everything, no local models.** Simplest, best quality out of the box. Every developer needs a key, every test run risks cost, and self-hosting, part of what the project explores, is given up.

The full comparison is in the study note.

## Decision

`packages/rag` defines three protocols in `providers/base.py`: `LLM.stream(messages)`, `Embedder.embed(texts)` (which also reports its `dimension`) and `Reranker.rerank(query, documents)`. The API and the worker pick an implementation from settings (`LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `OLLAMA_URL`). Today that is deterministic fakes for tests and load tests and Ollama adapters for local use; hosted providers come later, chosen by the eval results (ADR 0005).

## Why

Free hosting rules out self-hosting in production, and cost rules out hosted models in development, so the app needs one code path that can use either. Tests are the strongest reason: a fake behind the same contract lets the real chat and ingestion routes run with no model.

Protocols rather than base classes, so a vendor adapter imports nothing from our package and `mypy` still checks the match. Our own interfaces rather than option C, because they are three methods in total, the Ollama adapters are about 90 lines of standard library, and a dependency costs more to review than the code it saves.

The decision rests on these assumptions: the three kinds of model are all the app needs; every provider can stream text and return vectors of a fixed length; the eval will choose the hosted models, so choosing early would be a guess. It would change if the number of hosted vendors grows past two or three (reconsider option C), or if a model kind appears that the three contracts cannot express.

## Consequences

- Easier: local and production differ only in configuration; load tests measure this system, not a vendor, at no cost; a provider can be swapped or self-hosted without touching callers.
- The interface does not hide the embedding dimension. The vector column is fixed at 1024 (`EMBEDDING_DIM`); `OllamaEmbedder` raises on a mismatch, but a model of another size means a migration and re-embedding every chunk.
- Vectors from different embedding models are not comparable, and nothing enforces that the API uses the model the worker ingested with; the settings only document it.
- There is no real reranker yet: `HybridRetriever` accepts one, but only `FakeReranker` exists, so the API runs without reranking. A self-hosted one needs a model runtime and a lockfile change.
- Provider selection is a pair of `if` chains (`main.py`, `worker.py`); a third provider should move it into one shared function.
- The contracts have no error vocabulary: a timeout, a rate limit and a malformed reply are all plain exceptions, so callers cannot tell a retryable failure from a fatal one ([#53](https://github.com/phuchaitt3/book-rag-app/issues/53)).
- Next steps as load grows, in order: a hosted adapter on an async HTTP client (the Ollama adapter holds a thread per streamed answer, which caps concurrent answers at a few dozen); timeouts and retries with an error vocabulary in the contract; a rate limiter and a queue in front of the LLM. The `LLM` contract may also grow options and usage counts for cost tracking. The analysis is in the study note.

## Change log

- 2026-10-31: rewritten to the full template with options, consequences and the 1000x analysis ([#36](https://github.com/phuchaitt3/book-rag-app/issues/36)).
- 2026-11-01: rewritten to the short template; terms, options in depth and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
