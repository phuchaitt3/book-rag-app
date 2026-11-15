"""The identity dependency, and a walk that fails when a route has none (#230). No database."""

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient

from book_rag_api.auth import DEV_OWNER, DEV_USER_HEADER, current_owner
from book_rag_api.config import Settings
from book_rag_api.main import create_app

# Routes that carry no user data, named here on purpose: a new route is not exempt until
# someone adds it to this list in a reviewed change. The docs routes are FastAPI's own.
PUBLIC_PATHS = {
    "/healthz",
    "/readyz",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

UNREACHABLE_DB = "postgresql+asyncpg://x:x@127.0.0.1:1/x"
SOME_ID = "00000000-0000-0000-0000-000000000000"


def _depends_on(dependant: object, target: object) -> bool:
    if getattr(dependant, "call", None) is target:
        return True
    return any(_depends_on(d, target) for d in getattr(dependant, "dependencies", []))


def _walk(app: FastAPI) -> list[tuple[str, str, object | None]]:
    """(methods, path, dependant) of every route, routers included. The dependant is None for
    a route that is not an API route (the docs pages)."""
    return [
        (
            ",".join(sorted(ctx.methods or [])),
            ctx.path,
            getattr(ctx, "dependant", None),
        )
        for ctx in iter_route_contexts(app.routes)
    ]


def test_every_route_needs_an_identity_or_is_named_public() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DB))
    walked = _walk(app)
    assert {"/books", "/books/{book_id}/chat", "/ingestion-jobs/{job_id}"} <= {
        p for _, p, _ in walked
    }
    unguarded = [
        f"{methods} {path}"
        for methods, path, dependant in walked
        if path not in PUBLIC_PATHS
        and (dependant is None or not _depends_on(dependant, current_owner))
    ]
    assert not unguarded, (
        "these routes do not depend on `current_owner` (add `owner: Owner` and filter by it, "
        f"or name the path in PUBLIC_PATHS if it carries no user data): {unguarded}"
    )


def test_the_walk_catches_a_route_without_identity() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DB))

    @app.get("/leaky")
    async def leaky() -> list[str]:
        return []

    guarded = {p for _, p, d in _walk(app) if d is not None and _depends_on(d, current_owner)}
    assert "/leaky" not in guarded
    assert "/books" in guarded


def _client(environment: str) -> AsyncClient:
    app = create_app(Settings(database_url=UNREACHABLE_DB, environment=environment))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("environment", ["development", "test"])
async def test_dev_environments_refuse_a_request_without_the_header(environment: str) -> None:
    async with _client(environment) as client:
        response = await client.get("/books")
    assert response.status_code == 401


async def test_a_blank_header_is_no_identity() -> None:
    async with _client("test") as client:
        response = await client.get("/books", headers={DEV_USER_HEADER: "   "})
    assert response.status_code == 401


@pytest.mark.parametrize("environment", ["production", "staging", ""])
async def test_other_environments_ignore_the_header_and_refuse(environment: str) -> None:
    async with _client(environment) as client:
        calls = [
            client.get("/books", headers={DEV_USER_HEADER: DEV_OWNER}),
            client.get(f"/books/{SOME_ID}", headers={DEV_USER_HEADER: DEV_OWNER}),
            client.delete(f"/books/{SOME_ID}", headers={DEV_USER_HEADER: DEV_OWNER}),
            client.get(f"/ingestion-jobs/{SOME_ID}", headers={DEV_USER_HEADER: DEV_OWNER}),
            client.post(
                f"/books/{SOME_ID}/chat",
                json={"question": "hi"},
                headers={DEV_USER_HEADER: DEV_OWNER},
            ),
        ]
        for call in calls:
            assert (await call).status_code == 401


async def test_health_needs_no_identity() -> None:
    async with _client("production") as client:
        assert (await client.get("/healthz")).status_code == 200
