# 0002: PostgreSQL with pgvector and full-text search

**Status:** Accepted

## Context
Retrieval needs vector similarity and keyword matching (hybrid search), plus ordinary relational data for books, sections, chunks and jobs. Dedicated vector databases (Pinecone, Qdrant, Weaviate) are an option.

## Decision
Use PostgreSQL with `pgvector` (HNSW index) and Postgres full-text search (`tsvector`) in one database. Embeddings are 1024-dimensional (bge-m3). Locally the database is `pgvector/pgvector:pg17` in Docker Compose; in production it is Neon.

## Consequences
- One system to run, back up and scale; chunks and their metadata share a transaction.
- No separate vector store to pay for. If scale demands it, a dedicated store can replace retrieval behind the same interface (see 0003).
- The embedding dimension is part of the schema; changing to an embedder with a different dimension needs a migration and a re-embed.
