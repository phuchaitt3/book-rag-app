---
name: ADR review
about: The owner's review of an agent-decided ADR (study-design mode); it does not block work
title: "Review ADR NNNN: "
labels: adr-review
assignees: phuchaitt3
---

**ADR:** link to `docs/adr/NNNN-<slug>.md`

Part of the study-design mode (see [docs/design/README.md](https://github.com/phuchaitt3/book-rag-app/blob/main/docs/design/README.md)): agents decided and built this, and the review does not block work. Add the issue to the "ADR review" milestone.

## What to do
1. Read the ADR and the sources it lists.
2. Question it here as an outsider: why this and not X, what was assumed, what breaks first.
3. An agent answers each question here. When a question exposes a gap or a wrong call, the agent fixes or supersedes the ADR in a PR that says `Part of #<this issue>`, and records the question and answer in the ADR's "Review" section. To overrule the decision, say so here; that means a follow-up change.

The review is done when your questions are answered; the last PR says `Closes #<this issue>`.

## Questions to start with
Two to four questions specific to this ADR.
