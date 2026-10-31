# 0007: The web app learns the API's shape from a generated OpenAPI file

**Status:** Accepted

**Decided by:** agents (in answer to [#46](https://github.com/phuchaitt3/book-rag-app/issues/46); no brief, the question is small enough to answer in the ADR)   **Review:** [#74](https://github.com/phuchaitt3/book-rag-app/issues/74), open

## Context

The project has two programs that talk over HTTP: the API (Python, FastAPI) and the web app (TypeScript, Next.js). The API decides what each request must contain and what each reply looks like: the *shape*, meaning field names, types and which fields may be missing. The web app has to agree with that shape exactly. If the API renames `page_count` to `pages`, the web app does not fail to compile; it shows an empty value or crashes in the browser. The two live in different languages, so no compiler checks them against each other. A written description both sides are held to is called a *contract*.

Today the contract does not exist. `apps/web/src/app/api-status.tsx` reads the API address from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) but hardcodes the path `/healthz` as a string, and nothing checks that the endpoint exists or that its reply has the shape the web app reads. That cost one health check so far. The next task, the upload page and streaming chat (#21), makes the web app depend on three real endpoints and one stream, so the cost starts to grow with every field.

What the API offers today (checked against `main`):

| Route | Reply |
|---|---|
| `GET /healthz` | `{"status": "ok"}`, typed in the code only as `dict[str, str]` |
| `GET /readyz` | a small status object, returned as a bare `JSONResponse`, so the code does not describe it |
| `POST /books` (multipart form: a PDF file, optional title, author, language) | `UploadedBook`: the book and the id of its ingestion job |
| `GET /books` | a list of `BookOut` |
| `GET /ingestion-jobs/{id}` | `IngestionProgress`: status, stage, error, and how many chunks are embedded |
| `POST /books/{id}/chat` (JSON: question, `top_k`) | a *server-sent event* stream: a way for a server to push a series of messages down one open HTTP reply. Events: `citations` once, then many `token`, then `done` or `error` |

Three of the routes are fully typed: `POST /books`, `GET /books` and `GET /ingestion-jobs/{id}` return Pydantic models (`UploadedBook`, `BookOut`, `IngestionProgress`), and the chat request is one too (`ChatRequest`). `/healthz` is typed only as a dictionary of strings, `/readyz` has no declared reply, and the stream is not described at all (see the Decision). FastAPI already turns the typed models into an **OpenAPI** document at `/openapi.json`: a machine-readable description (a JSON file) of every route, request and reply, following the OpenAPI standard. That file is the natural contract, because it is produced from the same Python models that produce the replies, so it cannot disagree with the code.

Numbers (today, and at 1000x, meaning ten times the team and a public API; these are assumptions, nothing here has been measured):

| | Now | At 1000x |
|---|---|---|
| Routes the web app uses | 3 JSON routes and 1 stream | dozens |
| Clients | 1 (the web app) | several: web, mobile, scripts, outside developers |
| People changing the API | 1 | many, in parallel, in different time zones |
| Cost of a wrong guess about the shape | a broken page found by hand | a broken release, or a broken customer integration |

Constraints: one developer; the repo's CI already runs Python and web checks as separate jobs; adding a package means a lockfile change, which this repository treats as its own task (see `CLAUDE.md`).

## Options considered

**A. Hand-written types in the web app.** A developer copies each reply shape into a TypeScript type by reading the Python models.
- Pros: nothing to build; no new tool.
- Cons: the copy goes stale the first time someone changes the API and forgets the web app. TypeScript then trusts a type that is wrong, so the error appears at runtime. Nothing in CI notices.
- Commits us to: keeping two descriptions in step by memory.

**B. Generate the types from the API's OpenAPI file, commit the generated files, and have CI check they are current (chosen).** A script asks the FastAPI app for its OpenAPI document, saves it as `openapi.json` in the repo, and a generator (`openapi-typescript`) turns it into TypeScript types. CI checks that what is committed is what the script would produce.
- Pros: one source of truth (the Python models). An API change that the web app does not follow becomes a visible diff in the pull request and, once the web app uses the types, a TypeScript error in CI. No runtime cost: the types vanish at build time.
- Cons: a generation step and one extra dev dependency. Generated files add lines to diffs. The types describe what the API *says* it returns, not what it actually returns, so a bug in the API that breaks its own promise is still invisible to this check.
- Commits us to: running the generator after every API change (a `pnpm` script, and a CI check that fails when someone forgets).

**C. Generate a full client and validate replies at runtime (for example a generated fetch client plus `zod` schemas).** The web app calls the API through generated functions, and every reply is parsed and checked as it arrives.
- Pros: catches a lying API as well as a stale type; wrong data is stopped at the edge instead of crashing in the middle of a component.
- Cons: more code in the browser, more dependencies, and a runtime cost on every reply. It also adds a failure mode: a harmless extra field can reject a good reply if the schema is strict.
- Commits us to: a bigger client layer. Worth it when the data is untrusted or the API is shared with third parties.

**D. Contract tests: drive the real API from its OpenAPI file (for example Schemathesis), or consumer-driven contracts (Pact).** A test generates requests from the file and checks that real replies match it; with Pact, the web app records the calls it makes and the API proves it still satisfies them.
- Pros: finds the "API lies about its own schema" bugs that B cannot see. Pact also tells the API author *which* client a change would break.
- Cons: needs a running API and database in the test, which is slower and more to maintain. Pact needs a broker or file exchange between two teams, which a one-person project does not benefit from.
- Commits us to: a test environment and, for Pact, a process between producer and consumer.

**E. Do nothing until more endpoints exist.** The earlier recommendation in #46.
- Pros: no work now.
- Cons: the trigger it named ("when the first real endpoint the web app depends on is built") has happened: the upload and chat endpoints are merged and #21 is next. Adding types after the web app is written means writing the wrong thing first and fixing it by hand.

## Decision

Use option B. The Python models stay the single source of the contract.

- A script in the API package prints the app's OpenAPI document. A `pnpm` script saves it as `apps/web/src/api/openapi.json` and generates `apps/web/src/api/schema.d.ts` from it with `openapi-typescript`.
- Both files are committed. CI keeps them current in two places, so no job needs both Python and Node: the existing Python job runs a test that fails if the committed `openapi.json` differs from what the API produces (`apps/api/tests/test_openapi.py`), and a step in the existing web job regenerates `schema.d.ts` from `openapi.json` and fails on any difference (#82).
- The web app builds requests and reads replies using the generated types, through one small module (`apps/web/src/api/client.ts`) that owns the base URL (`NEXT_PUBLIC_API_URL`, which `api-status.tsx` already reads) and the route paths, so the hardcoded `/healthz` moves there too.
- **The stream is the exception.** The OpenAPI document cannot describe a series of events, so the payload shapes of `citations`, `token`, `done` and `error` need another route into the same file. Today only the `citations` payload is a model (`Citation` in `routers/chat.py`); `token`, `done` and `error` are inline dictionaries passed to `sse(event, data: Any)`. The build gives each of them a Pydantic model (the JSON on the wire stays the same) and the export script adds their JSON Schema to the document's components. The web app's event parser then uses the generated types for each event. The exact mechanism is for the build (#77) to settle; the rule is that the models in Python remain the only place the shapes are written.
- Option D is not adopted now. Add Schemathesis against a test database when the API has a second client or when a bug of the "API broke its own schema" kind appears (see "At 1000x the load").

This ADR changes no code. The build (#77) makes one small API-side change: models for the stream's `token`, `done` and `error` payloads and for the two health replies, with the same JSON on the wire.

## Why

**Why generate (B over A).** The only argument for hand-writing is the missing tooling cost, and that cost is one dev dependency and a short script. Against it stands the failure mode of A: a silent mismatch found by a user. With one developer the two sides are changed by the same person, which makes forgetting the second edit *more* likely, not less, because nothing prompts for it.

**Why commit the generated files (not generate at build time).** A committed file turns an API change into a reviewable diff: the pull request shows exactly which fields appeared or disappeared, before anything runs. It also lets the web build and type check without Python installed, which keeps the web CI job as simple as it is. The cost is some noise in diffs; the CI check stops the files from going stale.

**Why not runtime validation yet (B over C).** Both sides are written and deployed by the same person from the same repository, so a stale type is the realistic risk and a malicious or buggy reply is not. Runtime validation pays off when the data crosses a trust boundary, and nothing here does. It can be added on top of B later, using the same generated schema, without undoing anything.

**Why not contract tests now (B over D).** The tests need a database and a running API in CI, which is real maintenance for a risk that has not shown up. Pact answers "which consumer does this break?", and there is one consumer.

**Why one source of truth in Python.** The API is the part that holds the data model and the validation, so its models describe the data best. Generating in that direction (Python to TypeScript) avoids writing the shape twice; the reverse direction has no equivalent tooling as mature.

Assumptions this rests on: FastAPI keeps producing OpenAPI from its models; `openapi-typescript` stays maintained (it is widely used, and the output is plain `.d.ts`, so replacing it costs little); the web app stays one client for now.

## Consequences

Easier:
- A breaking API change shows up in the PR that makes it, as a diff in `openapi.json` and, if the web app uses the changed part, as a TypeScript error in CI.
- The web app gets autocompletion and compile-time checking for every request and reply.
- The API address lives in one place.

Harder, and what it commits us to:
- **A new dev dependency (`openapi-typescript`) changes `pnpm-lock.yaml`.** Per `CLAUDE.md` that is its own task, one at a time, so the build is split: first the dependency and generation pipeline, then the screens that use it (#21).
- **The check proves the file is current, not that the API is truthful.** If a route returns something its model does not describe, the types are wrong in a way CI cannot see. That is the gap option D would close.
- **A stale file is a failing CI job, which is a cost for someone who changes the API often.** The remedy is one command (`pnpm gen:api`), and the CI message should say so.
- **The stream needs extra work** (above) and is the part most likely to drift. The event parser in the web app should have a test that feeds it a recorded sample of each event.
- **The versioning question is postponed.** With one client that is deployed together with the API, a breaking change is simply a pair of edits in one pull request. That stops being true as soon as a client is released separately (a mobile app on users' phones), at which point the API needs versions (`/v1`) and a rule on how long old ones live.
- **Errors are part of the shape too.** FastAPI replies to a failure with `{"detail": ...}`; the generated types cover declared error replies only if the routes declare them. The web app should treat any non-2xx reply as an error without trusting its body.

## At 1000x the load

Here the load is not traffic but the number of routes, clients and people changing the API.

What breaks first, in order:
1. **The committed `openapi.json` becomes a merge-conflict magnet.** With many people changing the API in parallel, every PR touches the same big file and conflicts on it. Next step: generate it in CI on the merge result instead of requiring it committed, and keep only the diff report as a PR comment; or split it per route group.
2. **Types are not enough once clients are not in this repository.** An outside developer, or a mobile app already installed on phones, cannot be fixed by a same-PR edit. Next step: version the API (`/v1`), keep old versions alive for a stated period, and run a *breaking-change detector* on the OpenAPI file in CI (tools such as `oasdiff` compare two versions and flag removed or changed fields) to block accidental breaks.
3. **The API breaks its own promise.** With many authors, some route will return something its model does not say. Next step: option D, Schemathesis run against a test database on each PR, which generates requests from the file and checks the replies; and runtime validation (option C) in clients that cannot trust the API.
4. **Several clients, several languages.** Generating TypeScript types is then one of several generators. The OpenAPI file becomes the product, published for others, and its quality (descriptions, examples, error shapes) matters.

## Read more

- OpenAPI Specification, the introduction and the "Schema Object" section: https://spec.openapis.org/oas/latest.html
- FastAPI documentation, "Generate Clients" and the OpenAPI pages: https://fastapi.tiangolo.com/advanced/generate-clients/
- `openapi-typescript` documentation: https://openapi-ts.dev
- Ian Robinson, "Consumer-Driven Contracts: A Service Evolution Pattern": https://martinfowler.com/articles/consumerDrivenContracts.html
- MDN, "Using server-sent events": https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events

## Review

Questions and answers go here, dated, from [#74](https://github.com/phuchaitt3/book-rag-app/issues/74). None yet.
