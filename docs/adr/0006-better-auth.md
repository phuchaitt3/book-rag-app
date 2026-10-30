# 0006: Better Auth, with users in our own Postgres

**Status:** Planned

**Decided by:** agents, before study-design mode; not yet reviewed by the owner

## Context
Uploading and per-user libraries need accounts. Hosted identity providers charge per user; Auth.js lacks two-factor and passkeys, and its documented pattern predates the Next.js 16 `proxy.ts` rename.

## Decision
Use Better Auth in the Next.js app, storing users in our own PostgreSQL and issuing JWTs through its JWT plugin. FastAPI verifies the tokens against the JWKS endpoint.

## Consequences
- No per-user fees and no extra vendor; the API stays stateless.
- We own the user table and its migrations.
- Auth code is security-sensitive, so changes to it are merged by the owner.
