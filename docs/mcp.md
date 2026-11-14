# MCP server

The book index is exposed as a [Model Context Protocol](https://modelcontextprotocol.io) server
over stdio, so an agent or editor can search a book and cite it. Code:
`apps/api/src/book_rag_api/mcp_server.py`.

Search uses the same hybrid retriever as the chat endpoint (`build_retriever` in
`book_rag_api.main`): vector and BM25 results fused with RRF, then the reranker. An agent sees the
ranking a chat answer is built from.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_book` | `query`, `book_id?`, `k=5` (1 to 20) | `book_id`, `book_title`, `passages[]`: `chunk_id`, `section`, `page`, `score`, `text` |
| `get_passage` | `chunk_id`, `context=0` (0 to 5) | `passage`, and `before[]` / `after[]` neighbours in book order |
| `cite` | `chunk_ids[]` (1 to 50) | `citations[]`: `chunk_id`, `book_title`, `section`, `page`, `citation` (e.g. `Title, Section, p. 12`) |

Results are structured JSON with an output schema. A bad request is an error result with a
message (`isError`), never a crash: empty query, `k` or `context` out of range, a malformed or
unknown id, a book still being ingested, no `book_id` when the index holds more than one book.

## Launch

The server needs the same database and provider settings as the API (`DATABASE_URL`,
`EMBEDDING_PROVIDER`, `OLLAMA_URL`, `RERANKER_PROVIDER`, ... see `.env.example`):

```sh
uv run python -m book_rag_api.mcp_server
```

It speaks the protocol on stdout and logs to stderr, so start it from a client, not by hand.

## Register in a client

Claude Code, from the repository root:

```sh
claude mcp add book-rag -- uv run --directory /path/to/book-rag-app python -m book_rag_api.mcp_server
```

Or the generic `mcpServers` form (Claude Desktop, Cursor, ...):

```json
{
  "mcpServers": {
    "book-rag": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/book-rag-app", "python", "-m", "book_rag_api.mcp_server"],
      "env": { "DATABASE_URL": "postgresql+asyncpg://bookrag:bookrag@localhost:5432/bookrag" }
    }
  }
}
```

## Tests

`apps/api/tests/test_mcp_server.py` drives the server with an in-process MCP client over the fake
providers and the mini-book fixture: no network, no GPU, no model. It lists the tools and calls
each one, including the error cases.
