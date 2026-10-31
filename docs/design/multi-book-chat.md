# Brief: asking a question across several books

**Needed for:** [#89](https://github.com/phuchaitt3/book-rag-app/issues/89)   **Status:** draft

## Problem

The chat endpoint answers about one book (`POST /books/{book_id}/chat`), and retrieval is filtered by that one `book_id`. A user with several books may want one question answered from a chosen few, or from all of them. This brief picks the scope and the shape of the change. It changes the `ChunkSearcher` interface ([ADR 0003](../adr/0003-model-provider-interfaces.md)) and the chat contract ([ADR 0007](../adr/0007-api-web-contract.md)), so the code waits for the owner's questions, not for an approval.

## Requirements

- Ask one question over a chosen set of books and get one streamed answer whose citations say which book each passage came from.
- Every chosen book must be fully ingested (the rule from [#81](https://github.com/phuchaitt3/book-rag-app/issues/81): the latest job `succeeded`).
- Latency stays close to the single-book case. Today a search touches one book's rows; the target is a set of at most 10 books, about 100,000 chunks (400 MB of vectors) searched through the existing indexes.
- At 1000x (millions of chunks) the set may not grow with the corpus. A fixed upper bound on the set keeps the per-question cost flat; searching everything does not (see [ADR 0002](../adr/0002-postgres-pgvector-hybrid-search.md), "At 1000x the load").

## Options

**A. A chosen set of books (`book_id = ANY(:ids)`), at most 10.**
One query with an `IN` list. The HNSW index with iterative scan ([#84](https://github.com/phuchaitt3/book-rag-app/issues/84)) already handles a filter; a set widens the filter, so more rows pass it and fewer scans are wasted.
- Pros: small change, cost bounded by the set size, the same indexes, and the same per-book readiness check applied to each id.
- Cons: the user must choose the books; a bad choice gives a worse answer than a search over everything.

**B. Every book at once.**
No `book_id` filter, so the whole corpus is searched.
- Pros: nothing to choose.
- Cons: the filter that keeps today's search small disappears. HNSW memory and latency grow with the corpus, and the 1000x problems in ADR 0002 arrive at the first large library. Answer quality also drops as unrelated books add noise.

**C. Route first: guess the relevant books, then do A.**
A cheap first step (a per-book summary embedding, or a title match) picks the top few books; then option A runs on them.
- Pros: gives "search everything" a bounded cost.
- Cons: a second retrieval stage to build, measure and keep in step; a wrong route silently loses the right book. It needs the eval set ([ADR 0005](../adr/0005-application-first-then-evals.md)) to judge.

## Recommendation

Option A now; C is the step to take if B is wanted later. B is not built, because it removes the one property that keeps the design cheap.

Shape of the change, in order:

1. **`packages/rag` and the searcher.** `ChunkSearcher.vector_search` and `text_search` take `book_ids: Sequence[UUID]` instead of one `book_id`; `RetrievedChunk` gains `book_id`; `HybridRetriever.retrieve` takes `book_ids`. A one-book call passes a one-element list, so existing behaviour and tests carry over. The SQL becomes `Chunk.book_id.in_(book_ids)`.
2. **API.** A new route `POST /chat` with `{question, top_k, book_ids}` (1 to 10 ids). It answers `404` for an unknown id and `409` (as in #81) naming each book that is not ready. `POST /books/{book_id}/chat` stays and calls the same code with one id, so the web app keeps working. Citations already carry `book_id` and `book_title`; the prompt gets the book title next to each passage number so the model can tell sources apart.
3. **Web.** The book list becomes a multi-select; the chat shows the chosen titles and the chips already show the book. The generated types change with the API (`pnpm gen:api`, [ADR 0007](../adr/0007-api-web-contract.md)).
4. **Check.** Extend the HNSW regression test (several books, only the chosen ones returned), and measure p95 search latency at 1, 5 and 10 books on the 400-chunk-per-book test data before claiming the bound.

## Risks and open points

- Fusion ranks chunks from different books on one scale; a long book can crowd out a short one. Per-book caps (take at most `top_k / 2` per book) are a cheap guard; whether it is needed is a question for the eval set.
- The prompt grows with source labels. Token cost per question rises slightly.
- A chosen set makes the `book_id` index less selective; the planner may prefer a sequential scan for large sets. Check the query plan at 10 books.

## Read before deciding

- [pgvector README, "Filtering" and "Iterative index scans"](https://github.com/pgvector/pgvector) for how an `IN` filter interacts with HNSW.
- [Postgres docs, "Row and array comparisons" (`ANY`)](https://www.postgresql.org/docs/current/functions-comparisons.html) for the SQL form and planner behaviour.
- [Pinecone, "What is a vector database": metadata filtering](https://www.pinecone.io/learn/vector-database/) for the trade-off between filter-then-search and search-then-filter.

## Follow-ups to file when the owner has questioned this brief

1. Searcher and retriever take `book_ids` (packages/rag, apps/api).
2. `POST /chat` with `book_ids`, readiness check per book, prompt labels.
3. Web multi-select.
