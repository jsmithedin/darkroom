from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import check_csrf
from app.auth.identity import ALL_SCOPES, READ, WRITE, Principal
from app.auth.sessions import SESSION_COOKIE, lookup_session
from app.auth.verifier import verify_bearer
from app.db import get_session

__all__ = [
    "READ",
    "WRITE",
    "Principal",
    "current_principal",
    "require_scope",
    "require_session_principal",
]

UNAUTHENTICATED = HTTPException(
    status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


async def current_principal(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> Principal:
    """Authenticate via `Authorization: Bearer drk_...` or the session cookie.

    A Bearer header that fails never falls back to the cookie. Bearer requests skip CSRF
    (nothing is sent ambiently); cookie requests on unsafe methods must pass CSRF checks.
    """
    auth = request.headers.get("authorization", "")
    if auth:
        scheme, _, raw = auth.partition(" ")
        principal = await verify_bearer(db, raw.strip()) if scheme.lower() == "bearer" else None
        if principal is None:
            raise UNAUTHENTICATED
        return principal

    cookie = request.cookies.get(SESSION_COOKIE)
    found = await lookup_session(db, cookie) if cookie else None
    if found is None:
        raise UNAUTHENTICATED
    session, _user = found
    check_csrf(request, session.csrf_token)
    return Principal(
        user_id=session.user_id,
        scopes=ALL_SCOPES,
        via="session",
        csrf_token=session.csrf_token,
    )


def require_scope(scope: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: authenticate, then require `scope` (write implies read)."""

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not principal.has(scope):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient scope: requires {scope}",
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
            )
        return principal

    return dependency


async def require_session_principal(
    principal: Annotated[Principal, Depends(current_principal)],
) -> Principal:
    """Browser sessions only. Used where a token must not be able to act (token management)."""
    if principal.via != "session":
        raise HTTPException(status_code=403, detail="This action needs a browser session")
    return principal
