# Design notes

The project runs in **build** mode (see `CLAUDE.md`; owner's decision, 2026-11-27). Until then it ran as a system design study, with a study note and an owner review issue for every ADR; the notes in this folder are history from that period and stay readable.

## How a design decision is made

1. **Decide and write (agent).** For a choice that changes the architecture (a new service, store, queue, protocol, data model, or a scaling or consistency choice) or is costly to reverse, an agent writes a short ADR in the template from [docs/adr](../adr/README.md), following the `workflow:adr` skill.
2. **Accept.** The ADR's status is `Accepted` in the PR that merges it (the merge is the acceptance gate; standard: Nygard 2011 via [Fowler](https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html); checked 2026-10-31). An ADR left `Proposed` on purpose says in its text what it is waiting for.
3. **Check (agent).** Where the decision rests on a performance claim, measure it; the ADR gets one line with the result and a link.

The owner may overrule any decision, which means a follow-up ADR. A study note (template below) is optional.

**Accepted ADRs are frozen.** An accepted ADR is a record of what was decided, when, and on which assumptions; it is not a status page (owner's decision, 2026-11-13, after agents re-edited ADR 0003 five times to keep it current; standard: Nygard 2011 and Azure Well-Architected, accepted records are append-only and a changed decision supersedes the old one; checked 2026-11-01). It is not edited because the code moved on, a later ADR touched the same area, or a gap it names was fixed. The only edits are a typo or broken link, the `Superseded by NNNN` status line with its link, and a dated clarification of wording that was unclear when written. Current state lives in the code and the issues. An agent that cites an ADR checks that its status is not Superseded and that the code still matches; where they disagree, the code and the newest ADR win, and the agent says so in the issue or PR instead of editing the old ADR.

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

The app's real traffic will be small. A study note, when written, has an "At 1000x the load" section, so the reasoning still covers scale, and the ADR's Consequences name the next step in one line.

## Measuring scale on a small budget

The 1000x sections are reasoning; where a decision rests on one of them, it is checked by measurement on one laptop, at no cost, following the `workflow:scaling-test` skill. The aim is to find where each part bends (the knee) and why, not to run at full size. (standard: standards/scaling-tests-on-a-budget in the owner's config register, checked 2026-11-01)

- **Fakes for every paid model.** Load tests use the fake providers from [ADR 0003](../adr/0003-model-provider-interfaces.md), given realistic latency (time to first token, delay per token) and the errors a vendor returns (429, 5xx, timeouts). A fake that answers instantly flatters the results. To turn it on, pass keyword settings: `FakeLLM(first_token_delay=0.3, token_delay=0.03, error_rate=0.02, seed=1)` and `FakeEmbedder(batch_delay=0.1, errors=[None, TimeoutError()])` (delays in seconds, all off by default; `errors` is a scripted sequence used first, then `error_rate` draws from `random.Random(seed)`, so a run repeats; errors are plain exceptions until #53). Starting figures, from the local Ollama measurement in [serving-latency.md](../benchmarks/serving-latency.md) (#259; `qwen2.5:3b-instruct` on a 6 GB laptop GPU, not a paid vendor): `first_token_delay` about 7.9 s (median gap between the citations event and the first token, mostly the model reading six passages), and about 0.5 s between first token and the end of a whole answer (median, one question at a time). The per-token delay is not recorded: that run did not count tokens, so `token_delay` has no measured value yet. A paid vendor's figures and its 429 and 5xx rates still need the small paid calibration run, which the owner approves first (#155, item 4 open). A fake measures this system, not the vendor's speed, quality or cost; those need a small paid run, which the owner approves first.
- **Synthetic data, ramped.** Data grows in steps (for example 10x, 30x, 100x) up to what the machine's memory allows, checked before each run (1 million 1024-number vectors is about 4 GB before the index). Synthetic data is labelled as such next to every number.
- **No straight-line extrapolation.** A small environment does not scale linearly. A study note reports the measured curve, the knee and the size where the numbers stop; anything beyond is marked as an estimate.
- **Cloud only to check the last step.** If a question needs more than the laptop (40 GB of vectors, a GPU), the owner approves a short run first: the full ramp runs locally, then one cloud machine checks only the largest step and is destroyed when it ends.
- **What this cannot show:** real traffic patterns, a vendor's behaviour at volume, multi-region operation and the true cost per query. A study note names these as limits rather than claiming them.

## Study note template (optional)

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
