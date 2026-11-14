# Tracing (#225)

Metrics ([ADR 0010](../adr/), [slo.md](slo.md)) give aggregates: "first token p90 is 12 s". A trace shows where one request spent its time: embedding, vector search, BM25, rerank, the wait for the first token. It uses OpenTelemetry, so any OTLP backend works; the local one is Jaeger.

**Off by default.** Nothing is created unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. With it unset the API and worker build no tracer provider and no exporter, the SDK is not imported, and the manual spans are no-op calls (`book_rag.tracing.NoopTracer`). A test (`apps/api/tests/test_tracing.py`) fails if an exporter is created while it is off.

## Turn it on locally

```sh
docker compose -f compose.observability.yaml up -d jaeger     # UI http://127.0.0.1:16686
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318      # OTLP over HTTP
uv run uvicorn book_rag_api.main:app                          # and, for ingestion: uv run python -m book_rag_worker run
```

Ask a question in the web app, then pick service `book-rag-api` (or `book-rag-worker`) in Jaeger and find the trace. Jaeger keeps traces in memory and binds only to 127.0.0.1; there are no secrets in the compose file. The same two lines go in `.env` for the Compose stack (`OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318` from inside a container). A real collector needs its own auth and a trusted network; that is a deploy decision and is not part of this change. The compose file has not been started by the agent that wrote it (no running Docker daemon assumed); the first `up` is the test.

## Span tree of one chat request

```
POST /books/{book_id}/chat              server span (FastAPI instrumentation)
├─ SELECT ...                            SQLAlchemy: book lookup, latest ingestion job
├─ embed_query                           book_id
├─ vector_search                         book_id, k (candidates asked for), candidates (returned)
│  └─ SELECT / SET                       SQLAlchemy statements of the pgvector query
├─ lexical_search                        book_id, k, candidates   (runs at the same time as vector_search)
│  └─ SELECT                             SQLAlchemy statements of the BM25 query
├─ fuse                                  book_id, vector_candidates, lexical_candidates, fused_candidates, top_k
├─ rerank                                book_id, candidates, fallback (true when the reranker failed or timed out)
└─ llm.stream                            book_id, citations, pieces (the whole streamed answer)
   └─ llm.first_token                    start of the stream to the first piece
```

Spans appear only for the steps that ran: `rerank` is absent without a reranker, and a question the system abstains on has no `llm.stream`. The `http send` and `http receive` spans are the ASGI instrumentation's own and are noise for this purpose. The test pins this tree, with the fake providers (#155) and an in-memory span exporter.

Ingestion (worker, one trace per job, service `book-rag-worker`):

```
ingest.job                               job_id, attempts
├─ ingest.parse                          book_id, pages
├─ ingest.chunk                          book_id, chunks
├─ ingest.store                          book_id, chunks    (replace rows, BM25 statistics)
└─ ingest.embed                          book_id, chunks, batches
```

A failed job's span records the exception. The ingestion job does not carry the trace of the upload request that queued it (no propagation through the queue yet); the two share `book_id` and `job_id`.

## Logs and traces

With tracing on, every JSON log line written inside a span carries `trace_id` (32 hex digits, the ID Jaeger shows), next to `request_id`. Search Jaeger by that ID, or take the `trace_id` of a log line from a failing request.

## Example trace

[traces/chat-request.json](traces/chat-request.json) is one chat request, exported as JSON (name, ids, parent, start, duration, status, attributes per span, sorted by start). How it was produced: `uv run python scripts/export_chat_trace.py` starts a throwaway pgvector container, loads a two-chunk book, builds the API with the fake embedder, fake LLM and fake reranker and an in-memory span exporter, sends one question, and writes the spans. It is a real run of the real code path, not a hand-written file, but it has no real model latency: the durations show the shape of the trace and the cold-start cost of the first SQL statements, not what a user sees. A trace of a real Ollama request with numbers belongs under `docs/benchmarks/` with its script and conditions; none has been taken yet.

## Notes

- SQL spans use the instrumentation's `EngineTracer` attached to the one engine, not `SQLAlchemyInstrumentor().instrument()`: the latter refuses SQLAlchemy 2.1 (it checks `< 2.1.0`) and patches `create_engine` for the whole process. Revisit when the instrumentation supports 2.1.
- The provider is never set as the process-wide one, so tests can build their own; code gets its tracer from the app (`app.state.tracer`) or from `book_rag_worker.ingest.set_tracer`.
- The MCP server does not trace yet.
