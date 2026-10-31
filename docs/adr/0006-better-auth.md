# 0006: Better Auth, with users in our own Postgres

**Status:** Planned

**Decided by:** agents   **Review:** [#39](https://github.com/phuchaitt3/book-rag-app/issues/39), open

## Context

Uploading books and keeping a personal library need accounts: the app must know who a request comes from, and must only show a user their own books. Two words used below:

- **Authentication** is proving who you are (a password, a passkey, a Google sign-in). **Authorization** is deciding what that person may do.
- A **session** is the server remembering that you signed in, usually by a cookie that holds an ID. A **token** (here a JWT, JSON Web Token) is a signed note that carries the identity itself, so whoever receives it can check the signature without asking a database.

The system has two separate programs: a Next.js web app (the part users see) and a FastAPI API (books, ingestion, chat). Both must agree on who the user is.

What is built today: nothing. The API has no user concept, and the `books` table has no owner column (checked in `apps/api/src/book_rag_api/models.py`). The web app has no sign-in. That is why the status is *Planned*.

| Need | Today | At 1000x |
|---|---|---|
| Sign-in methods | email and password; a social sign-in (Google) would be welcome | the same, plus two-factor (a second proof such as a code) and passkeys (sign in with a fingerprint or device key) as users ask |
| Users | the owner and a few testers | tens of thousands; sign-ups and logins arrive in bursts |
| Cost | no fixed monthly fee for a hobby project | cost grows with users, not with a plan we chose |
| API stays stateless | the API runs as copies behind a load balancer and can restart any time | many copies; none may need a shared in-memory session |
| Data isolation | a user never sees another user's books or chats | the same, and provably |
| Next.js 16 | the web app is on Next.js 16.4 (`apps/web/package.json`), where the old `middleware.ts` file was renamed `proxy.ts` | |

## Options considered

**A. A hosted identity service (Clerk, Auth0, WorkOS and similar).** The vendor runs sign-in pages, stores the users and issues tokens.
- Pros: least work; two-factor, passkeys, bot protection and compliance come ready; no auth code to secure.
- Cons: usually free up to a threshold of monthly active users, then billed per user. Users live in the vendor's database, so our own tables can only point at an external ID, and moving away later means exporting users and, for password logins, often forcing a reset. An outage at the vendor locks everyone out.
- Commits us to: the vendor's pricing, data model and sign-in screens.

**B. Auth.js (formerly NextAuth) in the Next.js app.** An open-source library that runs inside the web app.
- Pros: free, no vendor, users can live in our Postgres, widely used.
- Cons: no built-in two-factor for username and password sign-in (a time-based code or an email code is code we write, or comes from community examples), and its [WebAuthn (passkey) provider](https://authjs.dev/getting-started/authentication/webauthn) is documented as "experimental and not recommended for production use", so two things we want would be code we write. Both were checked in the docs on 2026-10-31; the docs do not state a version. The first draft of this ADR also said Auth.js's setup predates the Next.js 16 `proxy.ts` rename; that is no longer true, since its [route-protection guide](https://authjs.dev/getting-started/session-management/protecting) now documents `proxy.ts`, so it is not a reason against B. Its session is designed to be read by the Next.js app, so the separate FastAPI service needs extra work (a token format and a verifier) to trust it.
- Commits us to: building two-factor ourselves, or switching later.

**C. Better Auth in the Next.js app, users in our Postgres, JWTs for the API (chosen).** Better Auth is an open-source TypeScript library that runs inside the web app. It stores users, sessions and linked accounts in tables in our database, offers two-factor, passkeys and social sign-in as plugins, and has a JWT plugin that signs short-lived tokens and publishes its public keys at a URL (a *JWKS* endpoint, JSON Web Key Set).
- Pros: no per-user fee and no extra vendor; features we want are plugins; we own the data; FastAPI verifies tokens with the public keys and needs no session store.
- Cons: we run and secure the auth code and the tables ourselves; email delivery (verification, password reset) needs its own provider; a younger library than Auth.js or the hosted vendors.
- Commits us to: a schema we share with a library, and to security patching.

**D. Write our own auth in FastAPI (passwords, sessions, tokens).**
- Pros: full control; no library.
- Cons: password hashing, reset flows, rate limiting, session fixation and token theft are all easy to get subtly wrong. Nothing here is a reason the project needs custom behaviour, so this is cost without benefit.

## Decision

Use Better Auth in the Next.js app. It stores users in our own PostgreSQL and issues JWTs through its JWT plugin. FastAPI verifies each token's signature against the JWKS endpoint and reads the user ID from it.

## Why

- **Cost and lock-in rule out A for a project that should stay free to run.** The user table is the hardest thing to move later, so we keep it in a database we control.
- **Two-factor and passkeys rule out B**, because they are needed eventually and are plugins in C. The API being a separate FastAPI service makes C's tokens a better fit than a cookie only the web app can read.
- **D is ruled out by risk, not by effort.** A maintained library is reviewed by many more people than our own code would be.
- **Tokens suit a stateless API.** FastAPI checks a signature with a cached public key; there is no session lookup per request, so the API copies need no shared state. The browser keeps a normal cookie session with the web app, and the web app obtains a short-lived token to call the API.
- Assumptions this rests on: Better Auth stays maintained and keeps its JWT plugin; one Postgres is enough for users (ADR 0002); the API is called from the web app, not by third-party clients. If a hosted vendor's free tier proves large enough and the second assumption weakens, A becomes reasonable again.

## Consequences

Easier:

- No per-user fees and no extra vendor; the API stays stateless.
- We own the user table and its migrations.

Harder, and what it commits us to:

- **Auth code is security-sensitive**, and it involves secrets (signing keys, OAuth client secrets), so changes to it are merged by the owner (see `CLAUDE.md`, "Pull requests").
- **Two programs write to one database.** Better Auth creates and migrates its own tables (`user`, `session`, `account`, `verification`, `jwks`); the API migrates everything else with Alembic. Alembic's schema comparison (*autogenerate*) will want to drop tables it does not know. The fix is an [`include_object` hook](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) in the migration environment that returns `False` for the auth table names, so Alembic neither creates nor drops them. That is the plan, because it is a few lines in the same schema. The alternative, putting the auth tables in their own Postgres schema and filtering by schema with `include_name`, isolates them better but needs Better Auth to create its tables there, which I have not checked. `books` will also need an owner column that points at the user ID.
- **Tokens cannot be taken back.** A JWT stays valid until it expires, so a stolen token works for its lifetime. We keep the lifetime short (the plugin's default is 15 minutes, signed with EdDSA, per its docs) and rely on the session behind the web app for sign-out and ban; a token deny-list is the next step if that is not enough.
- **A new dependency in the API** to verify tokens, which means a lockfile change that this repository reviews as its own task.
- **Data isolation is a separate decision.** Verifying who the caller is does not by itself stop one user reading another's books. The two options are checks in the application (every query filters by the owner ID, enforced in one place) or Postgres row-level security (the database itself hides other users' rows, using a per-request setting). Application checks are simpler and are the first plan; row-level security is a defence in depth worth its own ADR before the hosted demo.

## At 1000x the load

Numbers are estimates to be measured. Suppose a few testers become tens of thousands of users with login bursts.

What breaks first:

1. **Database connections from the web app.** Next.js runs as many short-lived instances, and each sign-in opens a database connection. Without a pooler (a proxy that shares a few real connections among many clients) Postgres runs out of connections. Neon provides a pooler; Better Auth must use it.
2. **Rate limiting.** Better Auth limits sign-in attempts to stop password guessing, but its counters are [stored in memory by default](https://www.better-auth.com/docs/concepts/rate-limit) (docs read 2026-10-31). With many instances the limit is per instance and an attacker gets a multiple of it, so the counters must move to shared storage. The same page lists three: `storage: "database"` (a `rateLimit` table, created by the Better Auth migration), `"secondary-storage"` (a cache such as Redis, if one is configured) or a custom store. The database option is the first choice here, since there is no cache.
3. **Email.** Verification and reset emails need a sending service with a good reputation; a free SMTP account will throttle or be marked as spam.
4. **The `session` table** grows with every device and needs a cleanup job for expired rows.

What does not break: token verification in the API. It is a signature check against a cached public key, which scales with the number of API copies. Key rotation needs care: the API must refetch the JWKS when it sees an unknown key ID.

The next step beyond this is a dedicated identity service or a hosted vendor (option A), which at that scale may cost less than the engineering time to run auth ourselves.

## Read more

- [Better Auth: JWT plugin](https://www.better-auth.com/docs/plugins/jwt): how tokens are issued and how the JWKS endpoint is used to verify them.
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): cookies, expiry and what goes wrong with sessions.
- [RFC 7519: JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519): what a JWT contains and why it cannot be revoked by itself.
- [PostgreSQL: Row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html): how row-level security works, for the isolation decision.

## Review

Owner questions and answers go here, dated, newest last. Questions are asked in [#39](https://github.com/phuchaitt3/book-rag-app/issues/39).

- 2026-10-31 (not an owner question): the reviewer of the rewrite found that the Auth.js, rate-limit and Alembic claims were written from memory ([#71](https://github.com/phuchaitt3/book-rag-app/issues/71)). They are now checked against the docs and linked. One was wrong: Auth.js documents the Next.js 16 `proxy.ts` rename, so that reason against option B was removed. The decision is unchanged.
