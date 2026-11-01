# Study note: Better Auth, users in our own Postgres

**For:** [ADR 0006](../adr/0006-better-auth.md)   **Status:** decided in ADR 0006 (not built yet)

This note holds the teaching material behind ADR 0006. The ADR states the decision; this note explains the terms, compares the options in depth and works through what breaks at 1000x the load. It was moved out of the ADR on 2026-11-01 (#128); the text is the ADR's earlier wording, lightly trimmed.

## Problem

Uploading books and keeping a personal library need accounts: the app must know who a request comes from, and must only show a user their own books. The system has two separate programs: a Next.js web app (the part users see) and a FastAPI API (books, ingestion, chat). Both must agree on who the user is.

What is built today: nothing. The API has no user concept, and the `books` table has no owner column (checked in `apps/api/src/book_rag_api/models.py`). The web app has no sign-in.

## Terms

- **Authentication** is proving who you are (a password, a passkey, a Google sign-in). **Authorization** is deciding what that person may do.
- **Session.** The server remembers that you signed in, usually by a cookie that holds an ID.
- **Token (JWT, JSON Web Token).** A signed note that carries the identity itself, so whoever receives it can check the signature without asking a database.
- **JWKS (JSON Web Key Set).** A URL that publishes the public keys needed to check token signatures.
- **Two-factor.** A second proof of identity, such as a code. **Passkey:** sign in with a fingerprint or device key.
- **Connection pooler.** A proxy that shares a few real database connections among many clients. In *transaction mode* a client gets a different connection after each transaction.
- **Row-level security.** Postgres itself hides other users' rows, using a per-request setting.

## Requirements

| Need | Today | At 1000x |
|---|---|---|
| Sign-in methods | email and password; a social sign-in (Google) would be welcome | the same, plus two-factor and passkeys as users ask |
| Users | the owner and a few testers | tens of thousands; sign-ups and logins arrive in bursts |
| Cost | no fixed monthly fee for a hobby project | cost grows with users, not with a plan we chose |
| API stays stateless | the API runs as copies behind a load balancer and can restart any time | many copies; none may need a shared in-memory session |
| Data isolation | a user never sees another user's books or chats | the same, and provably |
| Next.js 16 | the web app is on Next.js 16.4 (`apps/web/package.json`), where the old `middleware.ts` file was renamed `proxy.ts` | |

## Options in depth

**A. A hosted identity service (Clerk, Auth0, WorkOS and similar).** The vendor runs sign-in pages, stores the users and issues tokens.
- Pros: least work; two-factor, passkeys, bot protection and compliance come ready; no auth code to secure.
- Cons: usually free up to a threshold of monthly active users, then billed per user. Users live in the vendor's database, so our own tables can only point at an external ID, and moving away later means exporting users and, for password logins, often forcing a reset. An outage at the vendor locks everyone out.
- Commits us to: the vendor's pricing, data model and sign-in screens.

**B. Auth.js (formerly NextAuth) in the Next.js app.** An open-source library that runs inside the web app.
- Pros: free, no vendor, users can live in our Postgres, widely used.
- Cons: no built-in two-factor for username and password sign-in (a time-based code or an email code is code we write, or comes from community examples), and its [WebAuthn (passkey) provider](https://authjs.dev/getting-started/authentication/webauthn) is documented as "experimental and not recommended for production use". Both were checked in the docs on 2026-10-31; the docs do not state a version. Its [route-protection guide](https://authjs.dev/getting-started/session-management/protecting) covers Next.js 16's `proxy.ts`, so the framework version is not a reason against B. Its session is designed to be read by the Next.js app, so the separate FastAPI service needs extra work (a token format and a verifier) to trust it.
- Commits us to: building two-factor ourselves, or switching later.

**C. Better Auth in the Next.js app, users in our Postgres, JWTs for the API (chosen).** An open-source TypeScript library that runs inside the web app. It stores users, sessions and linked accounts in tables in our database, offers two-factor, passkeys and social sign-in as plugins, and has a JWT plugin that signs short-lived tokens and publishes its public keys at a JWKS endpoint.
- Pros: no per-user fee and no extra vendor; features we want are plugins; we own the data; FastAPI verifies tokens with the public keys and needs no session store.
- Cons: we run and secure the auth code and the tables ourselves; email delivery (verification, password reset) needs its own provider; a younger library than Auth.js or the hosted vendors.
- Commits us to: a schema we share with a library, and to security patching.

**D. Write our own auth in FastAPI (passwords, sessions, tokens).**
- Pros: full control; no library.
- Cons: password hashing, reset flows, rate limiting, session fixation and token theft are all easy to get subtly wrong. Nothing here is a reason the project needs custom behaviour, so this is cost without benefit.

## Reasoning in depth

- **Cost and lock-in rule out A** for a project that should stay free to run. The user table is the hardest thing to move later, so we keep it in a database we control.
- **Two-factor and passkeys rule out B**, because they are needed eventually and are plugins in C. The API being a separate FastAPI service makes C's tokens a better fit than a cookie only the web app can read.
- **D is ruled out by risk, not by effort.** A maintained library is reviewed by many more people than our own code would be.
- **Tokens suit a stateless API.** FastAPI checks a signature with a cached public key; there is no session lookup per request, so the API copies need no shared state.
- **Tokens cannot be taken back.** A JWT stays valid until it expires. The lifetime is kept short (the [JWT plugin](https://www.better-auth.com/docs/plugins/jwt) defaults to 15 minutes and signs with EdDSA on the Ed25519 curve; docs read 2026-10-31).

## Two programs, one database: Alembic and Better Auth

Better Auth creates and migrates its own tables: the four [core tables](https://www.better-auth.com/docs/concepts/database) (`user`, `session`, `account`, `verification`) and the `jwks` table added by the JWT plugin. The API migrates everything else with Alembic, whose schema comparison (*autogenerate*) will want to drop tables it does not know.

The fix is an [`include_object` hook](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) in the migration environment that returns `False` for every table Better Auth creates. Those five tables are only the starting set: the `rateLimit` table (from the database rate-limit storage chosen under "At 1000x the load") and the tables added by the two-factor and passkey plugins join them. The filter is a hard-coded list kept in one named constant, not derived: how Better Auth's generated schema could be read automatically is unchecked. It is changed in the same pull request that enables a plugin or the database rate limit, so a table is never added without its entry.

The alternative is to put the auth tables in their own Postgres schema and filter by schema with `include_name`, which isolates them better. **Decided 2026-10-31 ([#86](https://github.com/phuchaitt3/book-rag-app/issues/86)): the public schema with the `include_object` filter.** The own-schema option rests on `search_path`, and the Better Auth [database docs](https://www.better-auth.com/docs/concepts/database) vouch only for its `migrate` command following it; the runtime queries, the JWT plugin and the two-factor and passkey tables are unchecked, and `search_path` is a session setting that a transaction-mode pooler does not carry over. A wrong guess would show up as a table created in one schema and queried in another, after auth is built. The filter list, by contrast, fails loudly in the same pull request that enables a plugin. Revisit if isolation is wanted (for example a separate database role that cannot read the application tables); that needs the runtime behaviour checked first.

## Data isolation

Verifying who the caller is does not by itself stop one user reading another's books. The two options are checks in the application (every query filters by the owner ID, enforced in one place) or Postgres row-level security (the database hides other users' rows, using a per-request setting). Application checks are simpler and are the first plan; row-level security is a defence in depth worth its own ADR before the hosted demo. It would need `SET LOCAL` inside each transaction behind a transaction-mode pooler.

## Measurements

None. The 1000x figures below are estimates to be measured.

## At 1000x the load

Suppose a few testers become tens of thousands of users with login bursts.

What breaks first:

1. **Database connections from the web app.** Next.js runs as many short-lived instances, and each sign-in opens a database connection. Without a pooler Postgres runs out of connections. Neon provides one ([PgBouncer in transaction mode](https://neon.com/docs/connect/connection-pooling), reached by adding `-pooler` to the host name; docs read 2026-10-31), so the web app should connect through it. Migrations must not go through the pooler: Better Auth's `migrate` command and the Alembic runs use the direct (unpooled) connection, as Neon's page advises, because DDL, advisory locks and session settings such as `search_path` behave differently through a transaction-mode pooler.
2. **Rate limiting.** Better Auth limits sign-in attempts to stop password guessing (by default 100 requests per 10 seconds for all endpoints, and a stricter 3 requests per 10 seconds on `/sign-in/email` and `/two-factor/*`). The limiter is on by default only in production; to try it locally, set `rateLimit.enabled` to `true`. Its counters are [stored in memory by default](https://www.better-auth.com/docs/concepts/rate-limit) (docs read 2026-10-31). With many instances the limit is per instance and an attacker gets a multiple of it, so the counters must move to shared storage. The same page lists three: `storage: "database"` (a `rateLimit` table, created by the Better Auth migration), `"secondary-storage"` (a cache such as Redis) or a custom store. The database option is the first choice here, since there is no cache.
3. **Email.** Verification and reset emails need a sending service with a good reputation; a free SMTP account will throttle or be marked as spam.
4. **The `session` table** grows with every device and needs a cleanup job for expired rows.

What does not break: token verification in the API. It is a signature check against a cached public key, which scales with the number of API copies. Key rotation needs care: the API must refetch the JWKS when it sees an unknown key ID.

The next step beyond this is a dedicated identity service or a hosted vendor (option A), which at that scale may cost less than the engineering time to run auth ourselves.

## Read more

- [Better Auth: JWT plugin](https://www.better-auth.com/docs/plugins/jwt): how tokens are issued and how the JWKS endpoint is used to verify them.
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): cookies, expiry and what goes wrong with sessions.
- [RFC 7519: JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519): what a JWT contains and why it cannot be revoked by itself.
- [PostgreSQL: Row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html): how row-level security works, for the isolation decision.
