"""Who is calling: the one place where authentication plugs in.

Every route that touches user data depends on `current_owner` and filters its queries by the
owner it returns. For now the identity is a dev header, honoured only in the `development` and
`test` environments; anywhere else a request has no identity and is refused with 401. When a
real login is wired in (ADR 0006), only this function changes: it verifies the token and
returns the user id, and nothing that calls it does.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from book_rag_api.config import Settings

DEV_USER_HEADER = "X-Dev-User"
# The owner of every book that existed before owners did (migration 0004), and the default
# identity of the web app in development.
DEV_OWNER = "dev-user"
DEV_ENVIRONMENTS = ("development", "test")
MAX_OWNER_LENGTH = 200


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def resolve_owner(settings: Settings, dev_user: str | None) -> str:
    """The caller's owner id, or a 401 when there is none."""
    if settings.environment not in DEV_ENVIRONMENTS:
        # No login exists yet, so outside development nobody is identified.
        raise _unauthorized("authentication is required")
    owner = (dev_user or "").strip()
    if not owner or len(owner) > MAX_OWNER_LENGTH:
        raise _unauthorized(f"send a valid {DEV_USER_HEADER} header")
    return owner


async def current_owner(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return resolve_owner(settings, request.headers.get(DEV_USER_HEADER))


Owner = Annotated[str, Depends(current_owner)]
