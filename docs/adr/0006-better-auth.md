# 0006: Better Auth, with users in our own Postgres

**Status:** Planned   **Date:** 2026-10-30
**Decided by:** agents   **Confidence:** medium
**Review:** [#39](https://github.com/phuchaitt3/book-rag-app/issues/39), open   **Study note:** [docs/design/0006-better-auth.md](../design/0006-better-auth.md)

## Context

Uploading books and keeping a personal library need accounts: the app must know who a request comes from and show a user only their own books. The system is two programs, a Next.js web app and a FastAPI API, and both must agree on who the user is.

Nothing is built: the API has no user concept, the `books` table has no owner column and the web app has no sign-in (checked in `apps/api/src/book_rag_api/models.py`, 2026-10-31). That is why the status is Planned.

Requirements: email and password sign-in, with Google sign-in welcome, and two-factor and passkeys later; no fixed monthly fee, and no cost that grows per user on a hobby project; the API stays stateless, running as copies that can restart any time; a user never sees another user's books or chats; the web app is on Next.js 16.4, where `middleware.ts` became `proxy.ts`. Users: the owner and a few testers now (estimate).

## Options considered

- **A. A hosted identity service** (Clerk, Auth0, WorkOS). Least work; two-factor and passkeys come ready. Free only up to a threshold of monthly active users, then billed per user; users live in the vendor's database, so leaving means exporting them and often forcing password resets.
- **B. Auth.js in the Next.js app.** Free, users can live in our Postgres. No built-in two-factor for password sign-in, its passkey provider is documented as experimental (checked 2026-10-31), and its session is made for the Next.js app, so FastAPI needs a token format and verifier built on top.
- **C. Better Auth in the Next.js app, users in our Postgres, JWTs for the API.** An open-source TypeScript library with two-factor, passkeys and social sign-in as plugins and a JWT plugin that publishes public keys at a JWKS URL. No per-user fee, and we own the data. We run and secure the auth code, need our own email provider, and the library is younger.
- **D. Our own auth in FastAPI.** Full control. Password hashing, reset flows, rate limiting and token theft are easy to get subtly wrong, and nothing here needs custom behaviour.

The full comparison is in the study note.

## Decision

Use Better Auth in the Next.js app. It stores users in our own PostgreSQL and issues JWTs through its JWT plugin. FastAPI verifies each token's signature against the JWKS endpoint and reads the user ID from it. Better Auth's tables stay in the `public` schema and Alembic skips them through an `include_object` filter with a hard-coded table list (decided 2026-10-31, [#86](https://github.com/phuchaitt3/book-rag-app/issues/86)).

## Why

Cost and lock-in rule out A for a project that should stay free to run; the user table is the hardest thing to move later, so it stays in a database we control. Two-factor and passkeys are needed eventually and are plugins in C but code we write in B. Because the API is a separate service, tokens fit better than a cookie only the web app can read. D is ruled out by risk, not effort: a maintained library is reviewed by many more people than our own code would be.

Tokens suit a stateless API: FastAPI checks a signature against a cached public key, with no session lookup, so API copies share no state. The browser keeps a normal cookie session with the web app, which obtains a short-lived token to call the API.

The decision rests on these assumptions: Better Auth stays maintained and keeps its JWT plugin; one Postgres is enough for users (ADR 0002); the API is called from the web app, not by third-party clients. If a hosted vendor's free tier proves large enough and the third assumption weakens, A becomes reasonable again.

## Consequences

- No per-user fees and no extra vendor; the API stays stateless; we own the user table and its migrations.
- Auth code is security-sensitive and involves secrets, so changes to it are merged by the owner (`CLAUDE.md`, "Pull requests").
- Two programs write to one database. Better Auth migrates its own tables (`user`, `session`, `account`, `verification`, `jwks`, later `rateLimit` and the two-factor and passkey tables); Alembic migrates the rest. The `include_object` list is one named constant in the migration environment, changed in the same pull request that enables a plugin, so a missing entry fails loudly. The own-schema alternative rests on `search_path`, which is unchecked for Better Auth's runtime and which a transaction-mode pooler does not carry over. Revisit if isolation is wanted. `books` will need an owner column pointing at the user ID.
- Tokens cannot be taken back: a JWT stays valid until it expires. Lifetime is short (the plugin defaults to 15 minutes, docs read 2026-10-31) and sign-out and ban rely on the session behind the web app; a deny-list is the next step if that is not enough.
- A new API dependency to verify tokens means a lockfile change, its own task.
- Data isolation is a separate decision: verifying the caller does not stop one user reading another's books. Checks in the application, enforced in one place, come first; Postgres row-level security needs its own ADR before the hosted demo.
- Next steps as load grows, in order: the web app connects through the pooler while migrations use the direct URL; rate-limit counters move to shared storage (`storage: "database"`); a transactional email provider; a cleanup job for expired sessions; token verification needs no change, but the API must refetch the JWKS on an unknown key ID. Beyond that, a hosted vendor (A). The analysis is in the study note.

## Change log

- 2026-10-31: rewritten to the full template; the Auth.js, rate-limit and Alembic claims were checked against the docs and linked, and a wrong reason against option B (the `proxy.ts` rename) was removed ([#71](https://github.com/phuchaitt3/book-rag-app/issues/71), [#75](https://github.com/phuchaitt3/book-rag-app/issues/75), [#79](https://github.com/phuchaitt3/book-rag-app/issues/79)). Decision unchanged.
- 2026-10-31: auth tables stay in the `public` schema with an `include_object` filter, not their own schema ([#86](https://github.com/phuchaitt3/book-rag-app/issues/86)).
- 2026-11-01: rewritten to the short template; terms, options in depth, the Alembic reasoning and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
