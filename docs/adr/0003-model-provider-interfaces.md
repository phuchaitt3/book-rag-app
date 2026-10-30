# 0003: Every model sits behind a provider interface

**Status:** Accepted

**Decided by:** agents, before study-design mode; not yet reviewed by the owner

## Context
Local development should use self-hosted models (bge-m3, bge-reranker-v2-m3), but those need several GB of RAM and slow cold starts, so a free production deployment cannot host them. Tests and load tests should not pay for or wait on real models.

## Decision
`packages/rag` defines protocols for the LLM (streaming), the embedder (reports its `dimension`) and the reranker. Implementations: a deterministic fake for tests and load tests, an Ollama provider for local use, and hosted providers for production, chosen by the evaluation results.

## Consequences
- Local and production differ only in configuration.
- Load tests measure this system, not a vendor, at no cost.
- A provider can be swapped or self-hosted later without touching callers.
