# Brief: chat history (follow-up questions)

**Needed for:** the "Chat history" checkbox of [#53](https://github.com/phuchaitt3/book-rag-app/issues/53)   **Status:** draft; the proposed default (option A, client-held history, with Q2 appended-query retrieval, no condense call) was implemented by the overnight run in the API (PR for #53), reversible by reverting that PR; the owner can still decide otherwise (B, Q3). The web chat now sends the last 6 messages as `history`; the follow-up eval set and the cap values' measurement are not done.

## Problem

`POST /books/{book_id}/chat` ([apps/api/src/book_rag_api/routers/chat.py](../../apps/api/src/book_rag_api/routers/chat.py)) answers one question per request. `ChatRequest` holds `question` and `top_k`; `build_messages` in [apps/api/src/book_rag_api/prompts.py](../../apps/api/src/book_rag_api/prompts.py) sends the model a system message and one user message (passages plus the question). Nothing earlier reaches the model, and retrieval runs on the raw question text. A follow-up such as "and what did he say about that in chapter 3?" has no subject for the model or for the search.

Two separate things must be decided, and they are independent:

1. **Where history lives** (client or server), which sets row growth, retention, deletion and owner isolation.
2. **How a follow-up becomes a retrieval query**, which sets latency, cost and answer quality.

The first changes the chat contract ([ADR 0007](../adr/0007-api-web-contract.md)) and possibly the data model; the second changes only the request path. Neither needs code until the owner has questioned this brief.

## Requirements

- A follow-up question is answered with the earlier turns in view, and its citations still come from retrieved passages of the chosen book.
- Per-owner isolation holds ([#230](https://github.com/phuchaitt3/book-rag-app/issues/230), `Book.owner_id` in [apps/api/src/book_rag_api/models.py](../../apps/api/src/book_rag_api/models.py), the `Owner` dependency in `apps/api/src/book_rag_api/auth.py`): one owner can never read, continue or delete another owner's history.
- The API stays stateless and horizontally scalable (README, "Goals and priorities", item 1): no per-process session memory.
- Request cost stays bounded however long a conversation grows. This is the main scaling property: the prompt must not grow without limit.
- A book deletion must remove its history (existing foreign keys use `ondelete="CASCADE"`; see `models.py`).
- Not measured yet: the prompt size, the latency of a model call, and the share of questions that are follow-ups. Nothing below states these as numbers.

## Options: where history lives

**A. The client sends prior turns (stateless server).**
`ChatRequest` gains `history: [{role, text}]`, capped (count and characters) by validation. The web app keeps the conversation in browser state.
- Pros: no table, no retention policy, no deletion path, nothing new to isolate; the API stays stateless; smallest change.
- Cons: history is lost on reload or on another device; the client can forge any earlier "assistant" turn, so the server must treat history as untrusted text (the prompt already treats passages that way, see `SYSTEM_PROMPT`); every request re-uploads the history; no server-side cache key for a conversation; no way to count or review conversations later.

**B. Server-stored conversations (Postgres, `conversation_id`).**
New tables `conversations(id, owner_id, book_id, created_at, ...)` and `messages(id, conversation_id, role, text, citations, created_at)`, with `ON DELETE CASCADE` from `books`. The request carries `conversation_id`; the server loads the last N turns by an indexed query.
- Pros: survives reload and devices; the server controls what history means (a client cannot forge it); allows later features (list, resume, delete a conversation, feedback on answers, replaying a question into the eval set).
- Cons: unbounded row growth (about two rows per question, plus citations) that needs a retention rule and, at 1000x, a partitioning or archiving plan; a write on the request path (or after the stream) and a read before it; owner and book checks on every access (filter by `owner_id`, as `chat` does for `Book` today); a deletion path and a privacy question (stored question text is user data); a new migration.

**C. Hybrid: client holds history, server stores nothing, but signs it.** Not recommended: a signed blob adds key management for the one risk (forged turns) that capping and untrusted-text handling already cover for A.

Either way the model sees at most the last K turns, truncated to a fixed character budget, so the token cost per request is bounded and does not depend on where the history is stored. Older turns are dropped, not summarised, in the first version (a rolling summary is another model call and another thing to evaluate).

## Options: turning a follow-up into a retrieval query

Retrieval ([ADR 0002](0002-postgres-pgvector-hybrid-search.md)) embeds and keyword-searches one string. The generation step can see the history in the prompt either way; the question is what string to search with.

**Q1. Search the raw question (today).** Zero added cost; fails on pronouns and ellipsis.

**Q2. Append the last turn(s) to the query** (previous question, optionally the start of the previous answer, joined to the new question). No extra model call and no added latency; deterministic and cache-able on the joined string. Risk: topic drift, because the old question's words dominate the embedding when the user changes subject, and a longer string dilutes keyword search.

**Q3. Condense with the LLM** into a self-contained question, then search with it. Best at pronouns and ellipsis in principle. Costs one extra model call before the first retrieval, so first-token latency rises by that call's time (the first-token histogram and SLO added in [#254](https://github.com/phuchaitt3/book-rag-app/issues/254) would show it), plus tokens per follow-up and a new failure mode (the condense call fails or rewrites the question wrongly). It can be skipped when there is no history, so a first question pays nothing. The condensed text, not the user's, is what gets embedded, so a cache keyed on the raw question no longer applies; one keyed on `(book_id, condensed question)` still can.

**Q4. Retrieve with both and fuse** (raw question plus appended or condensed form). Higher recall, double the search cost per question; a later step only if Q2 or Q3 alone is not enough.

## Measurement before choosing

The harness is [evals/answer_eval.py](../../evals/answer_eval.py): it sends each question through the real endpoint and scores citation hit, cited-answer hit, citation validity, answer overlap, abstention rate and false-abstain rate, with bootstrap intervals; CI gates a fake-provider run against [evals/baseline.json](../../evals/baseline.json). Those runs are single-turn, so **the test set has no follow-ups today**. Step one is a small follow-up set built on the existing book test set: each item is a chain of two or three questions where a later one depends on an earlier one, each follow-up paired with the self-contained question that has the same evidence sentence. This set and the rules below are fixed before any run, and the harness gains an optional `history` field per question.

Run each variant (Q1, Q2, Q3) on the same set with the real model and embedder (a local or paid run the owner approves first; the fake providers in CI only prove plumbing), and report the metrics the harness already has, on follow-up questions and on the single-turn set to catch regressions:

- Primary: citation hit rate on follow-ups, with the self-contained rewrite run as the upper bound.
- Guard: citation hit rate and false-abstain rate on the existing single-turn questions must not worsen beyond the bootstrap interval of the current run; otherwise the variant is rejected.
- Cost: added first-token latency (p50 and p95, from the first-token metric) and extra tokens per follow-up.

Decision rules, fixed in advance:

- If Q2's follow-up citation hit rate is within the bootstrap interval of Q3's, choose Q2 (no extra call).
- If Q3 beats Q2 outside the intervals, choose Q3 only if the added p95 first-token latency stays under a bound the owner sets (open question 3); otherwise Q2.
- If neither beats Q1 outside the interval, ship history in the prompt only and keep searching the raw question.
- For history location, no eval is needed; measure only if B is chosen: rows per question and the cost of the history read at 100,000 stored messages, following `workflow:scaling-test` (generated data, labelled as such).

## Recommendation (proposal; the owner decides)

- **History location: A now.** It keeps the API stateless, adds no data to retain, delete or isolate, and meets the stated requirement. Move to B when a feature needs it (reload-proof history, a conversation list, feedback), and then as its own ADR with a retention rule decided first.
- **Retrieval query: Q2 as the default, pending the measurement above**, with Q3 as the option if the follow-up set shows Q2 drifting. Q2 adds no model call, so first-token latency and cost per question stay as today.
- **Bounds either way:** a cap on the number of messages and on characters, set by validation on `ChatRequest`; the values are chosen after the measurement, not guessed here.
- **Shape of the change** (after approval): `ChatRequest.history`; `build_messages` takes prior turns as chat messages before the passages message; the retriever call uses the Q2 string; the web chat keeps the turns in state; the eval follow-up set and `history` support. Citations stay per answer and refer only to the current turn's passages.

## Risks and open points

- Prompt injection through history (client-forged assistant turns): treat history as untrusted, never place it in the system message.
- A long previous answer in a Q2 query can swamp the new question; the cap on what is appended is part of what the measurement tunes.
- Rate limiting is per client address (`chat_rate_limit` in `apps/api/src/book_rag_api/config.py`); a condense call (Q3) doubles model calls per question without being counted.
- If B is chosen, every user's question text is stored: the retention period and a delete-my-data path must be decided first.

## Open questions for the owner

1. Is reload-proof or cross-device history wanted now (B), or is in-session history enough (A)?
2. If B: how long are conversations kept, and may stored questions feed the eval set?
3. What added p95 first-token latency is acceptable for a condense call (Q3)?
4. Should the follow-up eval set be written by hand, or may an agent draft it for the owner to check?

## Read before deciding

- [LangChain, "Conversational RAG" (history-aware retriever, question condensing)](https://python.langchain.com/docs/tutorials/qa_chat_history/) for the condense pattern.
- [OWASP LLM Top 10, LLM01 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) for why client-supplied history is untrusted.
- [Postgres docs, "Table partitioning"](https://www.postgresql.org/docs/current/ddl-partitioning.html) for the growth plan if messages are stored.

## Follow-ups to file when the owner has questioned this brief

1. Follow-up eval set and `history` support in `evals/answer_eval.py`.
2. `ChatRequest.history` and prompt change (option A).
3. Web chat keeps turns and sends them.
