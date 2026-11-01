# 0007: The web app learns the API's shape from a generated OpenAPI file

**Status:** Accepted   **Date:** 2026-10-31
**Decided by:** agents (answering [#46](https://github.com/phuchaitt3/book-rag-app/issues/46))   **Confidence:** high
**Review:** [#74](https://github.com/phuchaitt3/book-rag-app/issues/74), open   **Study note:** [docs/design/0007-api-web-contract.md](../design/0007-api-web-contract.md)

## Context

The API (Python, FastAPI) and the web app (TypeScript, Next.js) talk over HTTP. The API decides the shape of each request and reply (field names, types, which fields may be missing), and the web app must agree exactly. They are in different languages, so no compiler checks them against each other: if the API renames `page_count` to `pages`, the web app shows an empty value or crashes in the browser. A written description both sides are held to is a contract.

Today there is none. `apps/web/src/app/api-status.tsx` hardcodes the path `/healthz`, and nothing checks the reply. The next task, the upload page and streaming chat ([#21](https://github.com/phuchaitt3/book-rag-app/issues/21)), makes the web app depend on three JSON routes and one server-sent event stream. Three of those routes and the chat request are already Pydantic models, and FastAPI turns them into an OpenAPI document at `/openapi.json`, so the natural contract is produced from the same models that produce the replies.

Constraints: one developer and one client now (assumptions, not measured); CI runs Python and web checks as separate jobs; a new package means a lockfile change, which this repository treats as its own task (`CLAUDE.md`).

## Options considered

- **A. Hand-written types in the web app.** Nothing to build. The copy goes stale the first time the API changes, TypeScript trusts a wrong type, and CI notices nothing.
- **B. Generate types from the API's OpenAPI file, commit the generated files, and have CI check they are current.** One source of truth, a reviewable diff for every API change, no runtime cost. The types describe what the API says it returns, not what it returns, and a generation step is added.
- **C. A generated client plus runtime validation (for example `zod`).** Catches a lying API as well as a stale type. More browser code and dependencies, and a strict schema can reject a good reply.
- **D. Contract tests (Schemathesis, or Pact).** Finds bugs where the API breaks its own schema. Needs a running API and database in the test; Pact needs a process between two teams.
- **E. Do nothing until more endpoints exist** (the earlier recommendation in #46). The trigger it named has happened: the upload and chat endpoints are merged.

The full comparison is in the study note.

## Decision

Use option B. The Python models stay the single source of the contract. A script in the API package prints the app's OpenAPI document; a `pnpm` script saves it as `apps/web/src/api/openapi.json` and generates `apps/web/src/api/schema.d.ts` with `openapi-typescript`. Both files are committed. The Python job runs a test that fails if `openapi.json` differs from what the API produces, and a step in the web job regenerates `schema.d.ts` and fails on any difference ([#82](https://github.com/phuchaitt3/book-rag-app/issues/82)), so no job needs both Python and Node. The web app uses the generated types through one module, `apps/web/src/api/client.ts`, which owns the base URL and the route paths.

The stream is the exception: OpenAPI cannot describe a series of events. The `citations`, `token`, `done` and `error` payloads each get a Pydantic model (same JSON on the wire) and their JSON Schema is added to the document's components; the mechanism is for the build ([#77](https://github.com/phuchaitt3/book-rag-app/issues/77)) to settle, and the rule is that the shapes are written only in Python. Option D is not adopted now.

## Why

The only argument for hand-writing is tooling cost: one dev dependency and a short script. Against it stands a silent mismatch found by a user, and with one developer changing both sides, forgetting the second edit is more likely, not less. Committed files turn an API change into a reviewable diff and let the web build and type check without Python installed.

Runtime validation (C) pays off when data crosses a trust boundary, and here both sides come from one repository and one person; it can be added on top of B later from the same schema. Contract tests (D) need a database and a running API in CI for a risk that has not shown up, and Pact answers "which consumer does this break?" when there is one consumer. Generating from Python to TypeScript avoids writing the shape twice; the reverse has no equally mature tooling.

The decision rests on these assumptions: FastAPI keeps producing OpenAPI from its models; `openapi-typescript` stays maintained (its output is plain `.d.ts`, so replacing it is cheap); the web app stays the only client. It would change when a client is released separately, or when a bug of the "API broke its own schema" kind appears.

## Consequences

- A breaking API change shows in the PR that makes it, as a diff in `openapi.json` and a TypeScript error in CI if the web app uses the changed part; the API address lives in one place.
- `openapi-typescript` changes `pnpm-lock.yaml`, its own task, so the build is split: the pipeline first, then the screens (#21).
- The check proves the file is current, not that the API is truthful; option D would close that gap. A stale file fails CI, and the remedy is one command (`pnpm gen:api`) that the CI message should name.
- The stream is the part most likely to drift; the web app's event parser should have a test that feeds it a recorded sample of each event.
- Versioning is postponed. With one client deployed together with the API, a breaking change is a pair of edits in one PR; a separately released client needs `/v1` and a rule on how long old versions live.
- Errors are part of the shape: FastAPI replies to a failure with `{"detail": ...}`, and the generated types cover error replies only if routes declare them. The web app treats any non-2xx reply as an error without trusting its body.
- Next steps as the API grows, in order: stop committing `openapi.json` where it causes merge conflicts (generate it in CI on the merge result); version the API and run a breaking-change detector such as `oasdiff`; Schemathesis on each PR and runtime validation in clients that cannot trust the API; publish the OpenAPI file as a product once there are several clients. The analysis is in the study note.

## Change log

- 2026-10-31: wording of the CI checks made precise: the Python job checks `openapi.json`, the web job checks `schema.d.ts` ([#77](https://github.com/phuchaitt3/book-rag-app/issues/77), [#82](https://github.com/phuchaitt3/book-rag-app/issues/82)).
- 2026-11-01: rewritten to the short template; the route table, options in depth and the 1000x analysis moved to the study note, the decision unchanged ([#128](https://github.com/phuchaitt3/book-rag-app/issues/128)).
