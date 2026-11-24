import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.identity import READ, WRITE
from app.auth.sessions import hash_token
from app.config import Settings
from app.main import create_app
from app.models import OAuthClient, OAuthToken, User
from app.services.tokens import create_pat
from tests.conftest import reset_db

HOST = "film.jamielab.uk"
RESOURCE = f"https://{HOST}/mcp"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def rpc_body(resp: Response) -> dict[str, Any]:
    """Responses may be plain JSON or a single SSE event."""
    if resp.headers["content-type"].startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in resp.text.splitlines() if ln.startswith("data:")]
        return json.loads(data[-1])  # type: ignore[no-any-return]
    return resp.json()  # type: ignore[no-any-return]


class McpEnv:
    """A running app plus helpers to mint credentials for the single test user."""

    def __init__(self, app: Any, engine: AsyncEngine, user: User) -> None:
        self.app = app
        self.engine = engine
        self.user = user

    def client(self, token: str | None = None) -> AsyncClient:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return AsyncClient(
            transport=ASGITransport(app=self.app), base_url=f"https://{HOST}", headers=headers
        )

    async def pat(self, *scopes: str, **extra: Any) -> str:
        async with AsyncSession(self.engine) as db:
            _, raw = await create_pat(
                db, self.user.id, "t", scopes or [READ], extra.get("expires_at")
            )
            return raw

    async def oauth_token(
        self,
        *scopes: str,
        resource: str = RESOURCE,
        expires_in: timedelta = timedelta(hours=1),
        revoked: bool = False,
    ) -> str:
        raw = "dro_" + secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        async with AsyncSession(self.engine) as db:
            if await db.get(OAuthClient, "claude") is None:
                db.add(
                    OAuthClient(id="claude", name="Claude", redirect_uris=["https://c.example/cb"])
                )
                await db.flush()
            db.add(
                OAuthToken(
                    client_id="claude",
                    user_id=self.user.id,
                    family_id=uuid4(),
                    access_token_hash=hash_token(raw),
                    refresh_token_hash=hash_token("drr_" + raw),
                    resource=resource,
                    scopes=sorted(scopes or (READ,)),
                    access_expires_at=now + expires_in,
                    refresh_expires_at=now + timedelta(days=30),
                    revoked_at=now if revoked else None,
                )
            )
            await db.commit()
        return raw

    async def initialize(self, token: str) -> Response:
        async with self.client(token) as c:
            return await c.post("/mcp", headers=HEADERS, json=INIT)


@pytest.fixture
async def mcp_env(
    test_settings: Settings, engine: AsyncEngine, migrated_db: str
) -> AsyncIterator[McpEnv]:
    async with engine.begin() as conn:
        await reset_db(conn)
    async with AsyncSession(engine) as db:
        user = User(email="me@example.com", name="Me", google_sub="sub-1")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    app = create_app(test_settings)
    app.state.engine = engine
    async with LifespanManager(app) as manager:
        yield McpEnv(manager.app, engine, user)


@pytest.fixture
def mcp_session(mcp_env: McpEnv) -> Callable[[str], Awaitable[AsyncClient]]:
    """Factory: an initialised MCP session (open client) for the given bearer token."""

    async def make(token: str) -> AsyncClient:
        c = mcp_env.client(token)
        resp = await c.post("/mcp", headers=HEADERS, json=INIT)
        assert resp.status_code == 200, resp.text
        c.headers.update(HEADERS | {"mcp-session-id": resp.headers["mcp-session-id"]})
        await c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        return c

    return make


__all__ = ["READ", "WRITE", "HEADERS", "INIT", "RESOURCE", "McpEnv", "rpc_body"]
