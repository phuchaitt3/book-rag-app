# 0005: Build the application first, then improve the RAG logic against an eval set

**Status:** Accepted

**Decided by:** agents, before study-design mode; not yet reviewed by the owner

## Context
The first version of this project (a university project) used techniques that are now two years old, and nothing proved they helped.

## Decision
Build the whole application end to end on a plain, current RAG baseline first. Add a small golden question set and an evaluation harness early. After that, change the retrieval logic one experiment per pull request (OCR, reranker on or off, chunk size, query rewriting) and keep a change only if the eval improves.

## Consequences
- The application is demonstrable early, and every later improvement becomes a measured number.
- Old techniques get a fair trial as experiments, not as assumptions.
