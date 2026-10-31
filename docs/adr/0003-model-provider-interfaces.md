# 0003: Every model sits behind a provider interface

**Status:** Accepted

**Decided by:** agents   **Review:** [#36](https://github.com/phuchaitt3/book-rag-app/issues/36), open

## Context

The app calls three kinds of model:

- an **embedder**, which turns a piece of text into a vector (a list of numbers, here 1024 of them) so that texts with similar meaning end up near each other;
- a **reranker**, which reads a question and a candidate passage together and scores how well the passage answers the question;
- an **LLM** (large language model), which writes the answer and sends it back a few words at a time (*streaming*), so the user sees text appear instead of waiting for the whole reply.

Each kind can run in two places: on the developer's own machine (self-hosted, through [Ollama](https://ollama.com), a program that runs open models locally) or on a vendor's servers (hosted, paid per use). The constraints that matter:

| Need | Today | At 1000x |
|---|---|---|
| Local development runs without a vendor account or a bill | one developer, a handful of books | not applicable |
| Self-hosted models fit the machine | `bge-m3` (embedder) is about 1.2 GB on disk; `qwen2.5:7b-instruct` (default chat model) about 4.7 GB; a reranker like `bge-reranker-v2-m3` is about the size of `bge-m3`. All three together need several GB of RAM and take seconds to load. | thousands of questions an hour need GPUs or a hosted vendor |
| A free deployment can host the app | free plans offer far less memory than the models above need, so production cannot self-host them | production pays a vendor per token |
| Tests and load tests are fast, deterministic and free | a unit test must not wait for a 7B model or pay for tokens | a load test of 1000 concurrent users must measure *our* code, not a vendor's latency or rate limit |
| Answer quality can be compared across models (ADR 0005) | the eval set (a fixed list of questions with known good answers) will score each model | same |

So the system must run with different models in different places, and must be testable with no model at all.

## Options considered

**A. Call the model library directly where it is needed (no interface).** The chat route calls `ollama` or a vendor SDK, the worker calls an embeddings endpoint, and so on.
- Pros: least code today; no abstraction to learn.
- Cons: every caller knows one vendor's request and response format. Tests need the real service or a mock of that vendor's HTTP calls, which breaks whenever the vendor changes. Switching vendors means editing every caller.
- Commits us to: a vendor choice in many places. The cost of that choice grows with each feature.

**B. One interface per kind of model, with swappable implementations (chosen).** `packages/rag` defines a small contract for each of the three kinds; the app depends only on the contract and is handed an implementation when it starts. This is the *ports and adapters* idea (also called hexagonal architecture): the core logic talks to a port (the contract), and each adapter plugs a real system into it.
- Pros: tests use a fake adapter; local and production differ only in configuration; a new vendor is one new class.
- Cons: a contract is a guess about what all implementations have in common, and it can leak (see Consequences). Selecting an implementation by name adds a little wiring code.
- Commits us to: keeping the contracts small and stable, because every implementation and every caller depends on them.

**C. A third-party abstraction layer (LiteLLM, LangChain or similar).** Use a library that already wraps many vendors behind one API.
- Pros: dozens of vendors work out of the box; no adapters to write for common ones.
- Cons: a large dependency whose own release cadence and bugs become ours. It covers LLM chat well, but an embedder that reports its dimension, a reranker, and fakes for tests would still need our own interfaces on top. It also needs a lockfile change, which this repository reviews as a separate task.
- Commits us to: the library's data model and upgrade path. It does not remove the need for option B, only the need to write the adapters.

**D. Pick one hosted vendor for everything and drop local models.**
- Pros: simplest; best answer quality out of the box.
- Cons: every developer needs an account and a key, every test run risks cost, and the project is tied to one vendor's prices and outages. This also gives up self-hosting, which is part of what the project is meant to explore.

## Decision

`packages/rag` defines three protocols in `providers/base.py`:

- `LLM.stream(messages)` returns the answer as an asynchronous stream of text pieces;
- `Embedder.embed(texts)` returns one vector per text and reports its `dimension`;
- `Reranker.rerank(query, documents)` returns one score per document, higher meaning more relevant.

A *protocol* (PEP 544) is Python's way of describing an interface by shape: any class with those methods qualifies, with no base class to inherit. Implementations today:

- `FakeLLM`, `FakeEmbedder`, `FakeReranker` (deterministic, no network, no cost) for unit tests and load tests;
- `OllamaLLM` and `OllamaEmbedder` for local use;
- hosted providers for production, chosen by the evaluation results (ADR 0005). None exist yet.

The API and the worker each choose the implementation from settings (`LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `OLLAMA_URL`).

## Why

- **Free hosting rules out self-hosting in production, and cost rules out hosted models in development.** Neither alone covers both places, so the app needs one code path that can use either. That is option B.
- **Tests are the strongest reason.** A fake behind the same contract lets the chat and ingestion tests run the real routes and worker with no model. The fakes are not trivial: `FakeEmbedder` hashes words into buckets so that texts sharing words really are closer, which lets retrieval tests check ordering.
- **Protocols over base classes**, because an adapter for a vendor SDK does not have to import or subclass anything from our package, and `mypy` still checks that it matches.
- **Our own interfaces over option C**, because the interfaces are small (three methods in total), the Ollama adapters are about 90 lines using only the standard library, and a dependency would cost more to review than the code it saves. This is the assumption to revisit if the number of hosted vendors grows past two or three.
- Assumptions this rests on: the three kinds of model are all the app needs; every provider can stream text and return vectors of a fixed length; the eval (ADR 0005) will choose the hosted models, so choosing early would be a guess.

## Consequences

Easier:

- Local and production differ only in configuration.
- Load tests measure this system, not a vendor, at no cost.
- A provider can be swapped or self-hosted later without touching callers.

Harder, and what it commits us to:

- **The interface does not hide the embedding dimension.** The database column that stores vectors is fixed at 1024 (`EMBEDDING_DIM` in `apps/api/src/book_rag_api/models.py`). `OllamaEmbedder` checks every reply against the expected dimension and raises on a mismatch, so a model that returns another size fails loudly instead of corrupting the index. But changing to such a model means a migration and re-embedding every chunk of every book. The `dimension` property makes the problem visible; it does not remove it.
- **Mixing embedding models is unsafe.** Vectors from two models are not comparable. The API's embedding model must be the one the worker used at ingestion; the settings only document this, nothing enforces it yet.
- **There is no real reranker.** The retrieval code accepts one (`HybridRetriever(reranker=...)`), but only `FakeReranker` exists, so the API runs without reranking. A self-hosted reranker needs a model runtime, which means a new dependency and a lockfile change.
- **Provider selection is a pair of `if` chains**, one in the API (`main.py`) and one in the worker (`worker.py`). That is fine for two providers; a third should move the choice into one shared function.
- **The contracts have no error vocabulary.** A timeout, a rate limit and a malformed reply are all plain exceptions, so callers cannot tell a retryable failure from a fatal one. The chat endpoint's follow-ups (#53) add timeouts and rate limits and will need this.

## At 1000x the load

Numbers here are estimates to be measured, not results. Suppose today's few questions an hour become thousands, with many users asking at the same moment.

What breaks first is the Ollama adapter, not the interface:

1. **Threads.** `OllamaLLM` reads the streamed response with blocking `urllib`, one `asyncio.to_thread` call per piece. A thread is busy whenever an answer is waiting for its next piece, which is most of the time, and Python's default pool has at most `min(32, CPU count + 4)` threads. A few dozen simultaneous answers would queue behind each other, even if the model server could take more.
2. **No limits or retries.** The adapter uses a fixed 300 second timeout and no retry, backoff or rate limit. A slow model makes every request wait the full time.
3. **The model server itself.** Ollama runs only a few requests in parallel per loaded model by default, and one machine has one GPU or CPU. At this scale the self-hosted path stops being an option, and production already uses a hosted vendor.

The next steps, in order: add a hosted-vendor adapter with an async HTTP client (no thread per stream), add timeouts and retries with an error vocabulary in the contract, then add a rate limiter and a queue in front of the LLM. The interface itself should survive: a hosted adapter is one more class behind the same three methods. What might change is the `LLM` contract, to carry options (temperature, maximum length) and usage counts for cost tracking.

## Read more

- [PEP 544: Protocols, structural subtyping](https://peps.python.org/pep-0544/): what a Python protocol is and how it differs from an abstract base class.
- Alistair Cockburn, [Hexagonal architecture (ports and adapters)](https://alistair.cockburn.us/hexagonal-architecture/): the origin of the pattern and why tests are its first benefit.
- Martin Fowler, [Test Double](https://martinfowler.com/bliki/TestDouble.html): the names for fakes, stubs and mocks, and when each is the right one.
- [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md): the `/api/chat` and `/api/embed` calls the local adapters use.

## Review

Owner questions and answers go here, dated, newest last. Questions are asked in [#36](https://github.com/phuchaitt3/book-rag-app/issues/36).
