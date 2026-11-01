# Study note: model provider interfaces

**For:** [ADR 0003](../adr/0003-model-provider-interfaces.md)   **Status:** decided in ADR 0003

This note holds the teaching material behind ADR 0003. The ADR states the decision; this note explains the terms, compares the options in depth and works through what breaks at 1000x the load. It was moved out of the ADR on 2026-11-01 (#128); the text is the ADR's earlier wording, lightly trimmed.

## Problem

The app calls models in three places. Where the code calls them, and how, decides whether it can run locally, in production and in tests with the same code.

## Terms

- **Embedder.** Turns a piece of text into a vector (a list of numbers, here 1024) so that texts with similar meaning end up near each other.
- **Reranker.** Reads a question and a candidate passage together and scores how well the passage answers the question.
- **LLM (large language model).** Writes the answer and sends it back a few words at a time (*streaming*), so the user sees text appear instead of waiting for the whole reply.
- **Self-hosted and hosted.** Self-hosted models run on the developer's machine through [Ollama](https://ollama.com), a program that runs open models locally. Hosted models run on a vendor's servers and are paid per use.
- **Ports and adapters (hexagonal architecture).** The core logic talks to a port (a contract); each adapter plugs a real system into it.
- **Protocol (PEP 544).** Python's way of describing an interface by shape: any class with the right methods qualifies, with no base class to inherit.
- **Fake.** A test stand-in with real, simple behaviour and no network. `FakeEmbedder` hashes words into buckets so that texts sharing words really are closer, which lets retrieval tests check ordering.
- **Eval set.** A fixed list of questions with known good answers, used to score each model (ADR 0005).

## Requirements

Sizes are from the Ollama model pages; traffic is an estimate. Written 2026-10-31.

| Need | Today | At 1000x |
|---|---|---|
| Local development runs without a vendor account or a bill | one developer, a handful of books | not applicable |
| Self-hosted models fit the machine | `bge-m3` (embedder) about 1.2 GB on disk; `qwen2.5:7b-instruct` (default chat model) about 4.7 GB; a reranker like `bge-reranker-v2-m3` about the size of `bge-m3`. Together they need several GB of RAM and seconds to load. | thousands of questions an hour need GPUs or a hosted vendor |
| A free deployment can host the app | free plans offer far less memory than the models need, so production cannot self-host them | production pays a vendor per token |
| Tests and load tests are fast, deterministic and free | a unit test must not wait for a 7B model or pay for tokens | a load test of 1000 concurrent users must measure *our* code, not a vendor's latency or rate limit |
| Answer quality can be compared across models (ADR 0005) | the eval set scores each model | same |

So the system must run with different models in different places, and must be testable with no model at all.

## Options in depth

**A. Call the model library directly where it is needed.** The chat route calls `ollama` or a vendor SDK, the worker calls an embeddings endpoint, and so on.
- Pros: least code today; no abstraction to learn.
- Cons: every caller knows one vendor's request and response format. Tests need the real service or a mock of that vendor's HTTP calls, which breaks whenever the vendor changes. Switching vendors means editing every caller.
- Commits us to: a vendor choice in many places, whose cost grows with each feature.

**B. One interface per kind of model, with swappable implementations (chosen).** `packages/rag` defines a small contract for each kind; the app depends only on the contract and is handed an implementation when it starts.
- Pros: tests use a fake adapter; local and production differ only in configuration; a new vendor is one new class.
- Cons: a contract is a guess about what all implementations have in common, and it can leak (the embedding dimension, no error vocabulary; see the ADR's Consequences). Selecting an implementation by name adds a little wiring code.
- Commits us to: keeping the contracts small and stable, because every implementation and every caller depends on them.

**C. A third-party abstraction layer (LiteLLM, LangChain or similar).**
- Pros: dozens of vendors work out of the box; no adapters to write for common ones.
- Cons: a large dependency whose release cadence and bugs become ours. It covers LLM chat well, but an embedder that reports its dimension, a reranker and fakes for tests would still need our own interfaces on top. It also needs a lockfile change, which this repository reviews as a separate task.
- Commits us to: the library's data model and upgrade path. It does not remove the need for option B, only the need to write the adapters.

**D. Pick one hosted vendor for everything and drop local models.**
- Pros: simplest; best answer quality out of the box.
- Cons: every developer needs an account and a key, every test run risks cost, and the project is tied to one vendor's prices and outages. It also gives up self-hosting, which is part of what the project is meant to explore.

### Why protocols and why not option C

A vendor SDK adapter does not have to import or subclass anything from our package, and `mypy` still checks that it matches. The interfaces are small (three methods in total) and the Ollama adapters are about 90 lines using only the standard library. This is the assumption to revisit if the number of hosted vendors grows past two or three.

## Measurements

None. The 1000x figures below are estimates to be measured, not results.

## At 1000x the load

Suppose today's few questions an hour become thousands, with many users asking at the same moment. What breaks first is the Ollama adapter, not the interface:

1. **Threads.** `OllamaLLM` reads the streamed response with blocking `urllib`, one `asyncio.to_thread` call per piece. A thread is busy whenever an answer is waiting for its next piece, which is most of the time, and Python's default pool has at most `min(32, CPU count + 4)` threads. A few dozen simultaneous answers would queue behind each other, even if the model server could take more.
2. **No limits or retries.** The adapter uses a fixed 300 second timeout and no retry, backoff or rate limit. A slow model makes every request wait the full time.
3. **The model server itself.** Ollama runs only a few requests in parallel per loaded model by default, and one machine has one GPU or CPU. At this scale the self-hosted path stops being an option, and production already uses a hosted vendor.

The next steps, in order: add a hosted-vendor adapter with an async HTTP client (no thread per stream); add timeouts and retries with an error vocabulary in the contract; then add a rate limiter and a queue in front of the LLM. The interface itself should survive: a hosted adapter is one more class behind the same three methods. What might change is the `LLM` contract, to carry options (temperature, maximum length) and usage counts for cost tracking.

## Read more

- [PEP 544: Protocols, structural subtyping](https://peps.python.org/pep-0544/): what a Python protocol is and how it differs from an abstract base class.
- Alistair Cockburn, [Hexagonal architecture (ports and adapters)](https://alistair.cockburn.us/hexagonal-architecture/): the origin of the pattern and why tests are its first benefit.
- Martin Fowler, [Test Double](https://martinfowler.com/bliki/TestDouble.html): the names for fakes, stubs and mocks, and when each is the right one.
- [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md): the `/api/chat` and `/api/embed` calls the local adapters use.
