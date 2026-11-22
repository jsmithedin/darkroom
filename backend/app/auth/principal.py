import uuid
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import check_csrf
from app.auth.sessions import SESSION_COOKIE, lookup_session
from app.db import get_session

READ = "films:read"
WRITE = "films:write"
ALL_SCOPES = frozenset({READ, WRITE})


@dataclass(frozen=True)
class Principal:
    """Who is calling and what they may do, whatever the credential."""

    user_id: uuid.UUID
    scopes: frozenset[str]
    via: Literal["session", "pat", "oauth"]
    token_id: uuid.UUID | None = None
    client_id: str | None = None
    csrf_token: str | None = field(default=None, repr=False)

    def has(self, scope: str) -> bool:
        """`films:write` implies `films:read`."""
        if scope in self.scopes:
            return True
        return scope == READ and WRITE in self.scopes


async def current_principal(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> Principal:
    """Authenticate the request. Cookie-authenticated unsafe methods must pass CSRF checks."""
    raw = request.cookies.get(SESSION_COOKIE)
    found = await lookup_session(db, raw) if raw else None
    if found is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session, _user = found
    check_csrf(request, session.csrf_token)
    return Principal(
        user_id=session.user_id,
        scopes=ALL_SCOPES,
        via="session",
        csrf_token=session.csrf_token,
    )
