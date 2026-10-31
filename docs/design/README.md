# System design study

This project has two goals: a working book Q&A app, and a way for its owner to learn system design by studying and questioning the real decisions behind it. The project runs in **study-design** mode (see `CLAUDE.md`): agents decide the architecture and write out the full reasoning; the owner reviews it from outside the loop and may overrule any decision (owner's decision, 2026-10-31; before that, the owner made the decisions).

## How a design decision is made

Work items live in GitHub issues, not in files. Each ADR has a review issue in the "ADR review" milestone, labelled `adr-review` and assigned to the owner. The review does not block work. The ADR text itself stays in [docs/adr](../adr/README.md), and a PR that updates it says `Closes #n` or `Part of #n`.

1. **Decide and write (agent).** When work needs a choice that changes the architecture (a new service, store, queue, protocol, data model, or a scaling or consistency choice), an agent writes the ADR in the full template from [docs/adr](../adr/README.md), for a reader new to system design: requirements with numbers, each real option with its trade-offs, why the others lost, what breaks at 1000x the load, and 2 to 4 sources to read. It explains each term on first use. A longer analysis may go in a brief in this folder (template below), linked from the ADR.
2. **Build (agent).** The agent implements the decision without waiting for the review. Details inside the agreed design are the agent's call.
3. **Review (owner).** The owner reads the ADR and questions it as an outsider, in the review issue: why this and not X, what was assumed, what breaks first. The agent answers there. When a question exposes a gap or a wrong call, the agent fixes the ADR or supersedes it, and records the question and answer in the ADR's "Review" section. The ADR counts as reviewed when the owner's questions are answered; the owner may overrule it, which means a follow-up change.
4. **Check (agent).** Where the decision rests on a performance claim, measure it (a load test, a query plan, an eval run) and add the numbers to the ADR.

ADRs 0002 to 0006 were written before the detailed template. Agents rewrite each one to the full template, one PR per ADR, so its review issue has the full reasoning to question. ADR 0001 was confirmed by the owner under the earlier process and stays as it is.

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

**Needed for:** <issue or milestone>   **Status:** draft | decided in ADR NNNN

## Problem
What has to be decided and why now.

## Requirements
Functional needs and non-functional targets, with numbers (current and at 1000x).

## Options
For each option: how it works, pros, cons, cost, what it commits us to.

## Recommendation
The agent's pick and why. The owner may question or overrule it in the ADR's review issue.

## Read before deciding
Two to four sources (docs, articles, book chapters) on the trade-off.
```
