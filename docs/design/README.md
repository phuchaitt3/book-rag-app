# System design study

This project has two goals: a working book Q&A app, and a way for its owner to learn system design by studying and questioning the real decisions behind it. The project runs in **study-design** mode (see `CLAUDE.md`): agents decide the architecture and write out the full reasoning; the owner reviews it from outside the loop and may overrule any decision (owner's decision, 2026-10-31; before that, the owner made the decisions).

## How a design decision is made

Work items live in GitHub issues, not in files. Each ADR has a review issue in the "ADR review" milestone, labelled `adr-review` and assigned to the owner. The review does not block work (standard: the ADR lifecycle proposed, accepted, superseded, where an accepted decision is active and a later change supersedes it rather than blocking the work, from Nygard 2011 via [Fowler](https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html) and the [GDS Way](https://gds-way.digital.cabinet-office.gov.uk/standards/architecture-decisions.html); the merge of the ADR's PR is the acceptance gate; checked 2026-10-31). The ADR text itself stays in [docs/adr](../adr/README.md), and a PR that updates it says `Closes #n` or `Part of #n`. The review issue stays open until the owner has finished questioning the ADR, so a PR that edits an ADR says `Part of #n` and never puts `close`, `fix` or `resolve` next to `#n`, even in "does not close #n": GitHub closes the issue on merge anyway (this closed the ADR 0002 review twice on 2026-10-31). A hook (`.claude/hooks/pr_close_guard.py`) refuses such a PR command.

1. **Decide and write (agent).** When work needs a choice that changes the architecture (a new service, store, queue, protocol, data model, or a scaling or consistency choice), an agent writes a short ADR in the template from [docs/adr](../adr/README.md) and a study note in this folder (template below), linked from the ADR. The note is for a reader new to system design: it explains each term on first use, compares each real option in depth, says what breaks at 1000x the load, and lists 2 to 4 sources to read. The ADR states the decision and why. A brief written before the decision becomes the decision's study note.
2. **Build (agent).** The agent implements the decision without waiting for the review. Details inside the agreed design are the agent's call.
3. **Review (owner).** The owner reads the ADR and questions it as an outsider, in the review issue: why this and not X, what was assumed, what breaks first. The agent answers there. When a question exposes a gap or a wrong call, the agent fixes the ADR or supersedes it, and adds one dated line to the ADR's change log. The question and answer stay in the issue; an answer that teaches something worth keeping also goes in the study note. The ADR counts as reviewed when the owner's questions are answered; the owner may overrule it, which means a follow-up change.
4. **Check (agent).** Where the decision rests on a performance claim, measure it (a load test, a query plan, an eval run). The method and raw numbers go in the study note; the ADR gets one line with the result and a link.

ADRs 0002 to 0008 were written before the short template. Agents rewrite each one to it, one PR per ADR: the decision unchanged, the teaching and measurements moved to a study note, the Review section replaced by a change log. ADR 0001 was confirmed by the owner under the earlier process and stays as it is.

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

The app's real traffic will be small. Every study note therefore has an "At 1000x the load" section, so the reasoning still covers scale, and the ADR's Consequences name the next step in one line.

## Measuring scale on a small budget

The 1000x sections are reasoning; where a decision rests on one of them, it is checked by measurement on one laptop, at no cost, following the `workflow:scaling-test` skill. The aim is to find where each part bends (the knee) and why, not to run at full size. (standard: standards/scaling-tests-on-a-budget in the owner's config register, checked 2026-11-01)

- **Fakes for every paid model.** Load tests use the fake providers from [ADR 0003](../adr/0003-model-provider-interfaces.md), given realistic latency (time to first token, delay per token) and the errors a vendor returns (429, 5xx, timeouts). A fake that answers instantly flatters the results. A fake measures this system, not the vendor's speed, quality or cost; those need a small paid run, which the owner approves first.
- **Synthetic data, ramped.** Data grows in steps (for example 10x, 30x, 100x) up to what the machine's memory allows, checked before each run (1 million 1024-number vectors is about 4 GB before the index). Synthetic data is labelled as such next to every number.
- **No straight-line extrapolation.** A small environment does not scale linearly. A study note reports the measured curve, the knee and the size where the numbers stop; anything beyond is marked as an estimate.
- **Cloud only to check the last step.** If a question needs more than the laptop (40 GB of vectors, a GPU), the owner approves a short run first: the full ramp runs locally, then one cloud machine checks only the largest step and is destroyed when it ends.
- **What this cannot show:** real traffic patterns, a vendor's behaviour at volume, multi-region operation and the true cost per query. A study note names these as limits rather than claiming them.

## Study note template

A study note is where the learning happens; the ADR stays short so the decision is easy to find. Before the decision the note is a brief (status `draft`); after it, it is the ADR's study note. Name it `NNNN-<slug>.md` after its ADR, or `brief-<slug>.md` while there is none.

```markdown
# Study note: <the question, in a few words>

**For:** ADR NNNN (or <issue> while undecided)   **Status:** draft | decided in ADR NNNN

## Problem
What has to be decided and why now.

## Terms
Each term a reader new to system design needs (HNSW, idempotency, connection pooling), in a sentence or two.

## Requirements
Functional needs and non-functional targets, with numbers (current and at 1000x), each marked measured or estimated.

## Options in depth
For each option: how it works, pros, cons, cost, what it commits us to.

## Measurements
Method, environment, raw numbers and what they do and do not show. Dated.

## At 1000x the load
What breaks first, in order, and the next step for each.

## Read more
Two to four sources (docs, articles, book chapters) on the trade-off.
```
