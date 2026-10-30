# Architecture decision records

Short records of choices that are costly to reverse. Each states the context, the decision and its consequences. *Accepted* means decided and in use; *Planned* means decided but not built yet.

| # | Decision | Status |
|---|---|---|
| [0001](0001-monorepo-uv-pnpm.md) | Monorepo with a uv workspace and a pnpm workspace | Accepted |
| [0002](0002-postgres-pgvector-hybrid-search.md) | PostgreSQL with pgvector and full-text search, no separate vector database | Accepted |
| [0003](0003-model-provider-interfaces.md) | Every model sits behind a provider interface | Accepted |
| [0004](0004-ingestion-queue-in-postgres.md) | Ingestion queue in Postgres (Procrastinate), no Redis | Planned |
| [0005](0005-application-first-then-evals.md) | Build the application first, then improve the RAG logic against an eval set | Accepted |
| [0006](0006-better-auth.md) | Better Auth, with users in our own Postgres | Planned |
