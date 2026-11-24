"""Shared plumbing for MCP tools: who is calling, and a database session per call."""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.identity import Principal
from app.auth.verifier import principal_from_access_token
from app.models.reference import RefKind
from app.services import reference as ref_svc

EngineGetter = Callable[[], AsyncEngine]


def caller(scope: str) -> Principal:
    """The authenticated principal, or a tool error if it lacks `scope`."""
    access = get_access_token()
    if access is None:
        raise ToolError("Not authenticated.")
    principal = principal_from_access_token(access)
    if not principal.has(scope):
        raise ToolError(f"This token lacks the {scope} scope.")
    return principal


@asynccontextmanager
async def tool_session(engine: EngineGetter) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine(), expire_on_commit=False)
    async with maker() as session:
        yield session


async def resolve_ref(db: AsyncSession, kind: RefKind, value: str | None) -> uuid.UUID | None:
    """Accept a name (case-insensitive) or an id, so the model need not look ids up first."""
    if value is None or not value.strip():
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    wanted = value.strip().casefold()
    for item in await ref_svc.list_items(db, kind, include_archived=True):
        if item.name.casefold() == wanted:
            return item.id
    raise ToolError(
        f"No {kind.value.rstrip('s')} named '{value}'. Use list_reference_data('{kind.value}')."
    )
