"""The API's OpenAPI document, the contract the web app's types are generated from (ADR 0007).

OpenAPI cannot describe a stream of events, so the chat endpoint's event payloads are added to
the document's schemas here. Run `python -m book_rag_api.openapi <file>` to write the document.
"""

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from book_rag_api.routers.chat import STREAM_EVENT_MODELS


def add_stream_events(app: FastAPI) -> None:
    """Make `app.openapi()` (and `/openapi.json`) include the chat stream's event schemas."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schemas = schema.setdefault("components", {}).setdefault("schemas", {})
            for model in STREAM_EVENT_MODELS:
                model_schema = model.model_json_schema(
                    ref_template="#/components/schemas/{model}", mode="serialization"
                )
                if model.__name__ in schemas:
                    raise ValueError(f"schema name {model.__name__!r} is already taken")
                schemas.update(model_schema.pop("$defs", {}))
                schemas[model.__name__] = model_schema
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def render(app: FastAPI) -> str:
    """The document as stable text (sorted keys), so a regenerated file differs only on a change."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def document_app() -> FastAPI:
    """The app as the document sees it: built from defaults, never from the environment.

    The document does not depend on settings, so a stray `DATABASE_URL` or an invalid value in
    the developer's or CI's environment can neither change nor break it. `model_construct` skips
    reading the environment and `.env` files; nothing connects until the app starts.
    """
    from book_rag_api.config import Settings
    from book_rag_api.main import create_app

    return create_app(Settings.model_construct())


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m book_rag_api.openapi <output file>")
    Path(sys.argv[1]).write_text(render(document_app()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
