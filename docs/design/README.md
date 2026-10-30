# System design study

This project has two goals: a working book Q&A app, and a way for its owner to learn system design by making the real decisions behind it. The project runs in **study-design** mode (see `CLAUDE.md`): agents prepare and implement, the owner decides the architecture.

## How a design decision is made

1. **Brief (agent).** When work needs a choice that changes the architecture (a new service, store, queue, protocol, data model, or a scaling or consistency choice), an agent writes a brief in this folder using the template below and stops for the owner. Other work goes on.
2. **Decision (owner).** The owner reads the brief and the suggested reading, picks an option (or a different one), and writes the ADR in [docs/adr](../adr/README.md) in their own words. The agent may correct facts in it, not the reasoning.
3. **Build (agent).** The agent implements the decision. Details inside the agreed design are the agent's call.
4. **Check (both).** Where the decision rests on a performance claim, measure it (a load test, a query plan, an eval run) and add the numbers to the ADR.

Decisions made before this mode started are ADRs 0001 to 0006, marked "agent-decided". Reviewing them is the first study step: for each, ask whether you would have chosen the same, what the alternatives were, and what breaks at 1000x the load. Then confirm the ADR in your own words or replace it.

## A framework for each feature

The usual structure of a system design discussion, applied to each milestone:

1. **Requirements:** what it must do, and the non-functional targets (latency, throughput, availability, cost), with numbers.
2. **Estimates:** rough sizes: books, pages, chunks, embeddings, storage, queries per second.
3. **API:** endpoints, request and response shapes, sync or async.
4. **Data model:** tables, keys, indexes, what must be consistent with what.
5. **High-level design:** components and how a request flows between them.
6. **Deep dives:** the one or two parts that are hard.
7. **Bottlenecks:** what fails first as load grows, and the next step.

## Where the topics appear in this project

| Part of the app | System design topics |
|---|---|
| Upload and ingestion (parse, chunk, embed) | async work off the request path, job queues, retries and idempotency, backpressure, object storage |
| Retrieval (vector and keyword search) | indexes (HNSW, full-text), hybrid ranking, caching, read scaling |
| Chat answers with citations | streaming (SSE), timeouts, rate limits, calls to slow external services |
| Deploy | stateless services, autoscaling, connection pooling, configuration and secrets |
| Evals and observability | measuring quality, tracing, SLOs, cost tracking |
| Auth | sessions, multi-tenancy, data isolation |

The app's real traffic will be small. Every ADR therefore ends with an "At 1000x the load" section, so the reasoning still covers scale.

## Brief template

```markdown
# Brief: <the question, in a few words>

**Needed for:** <issue or milestone>   **Status:** waiting for the owner | decided in ADR NNNN

## Problem
What has to be decided and why now.

## Requirements
Functional needs and non-functional targets, with numbers (current and at 1000x).

## Options
For each option: how it works, pros, cons, cost, what it commits us to.

## Recommendation
The agent's pick and why. The owner is free to choose differently.

## Read before deciding
Two to four sources (docs, articles, book chapters) on the trade-off.
```
