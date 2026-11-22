import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.main import create_app

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


@pytest.fixture
async def mcp_app(test_settings: Settings, engine: AsyncEngine) -> AsyncIterator[Any]:
    app = create_app(test_settings)
    app.state.engine = engine
    async with LifespanManager(app) as manager:
        yield manager.app


def client_for(app: Any, host: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=f"https://{host}")


async def test_initialize_with_allowed_host(mcp_app: Any) -> None:
    async with client_for(mcp_app, "film.jamielab.uk") as c:
        resp = await c.post("/mcp", headers=HEADERS, json=INIT)
        assert resp.status_code == 200, resp.text
        session = {"mcp-session-id": resp.headers["mcp-session-id"]}
        await c.post(
            "/mcp",
            headers=HEADERS | session,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        resp = await c.post(
            "/mcp",
            headers=HEADERS | session,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        tools = rpc_body(resp)["result"]["tools"]
        assert [t["name"] for t in tools] == ["ping"]


async def test_wrong_host_rejected(mcp_app: Any) -> None:
    async with client_for(mcp_app, "evil.example") as c:
        resp = await c.post("/mcp", headers=HEADERS, json=INIT)
        assert resp.status_code == 421


async def test_api_health_still_reachable(mcp_app: Any) -> None:
    async with client_for(mcp_app, "film.jamielab.uk") as c:
        resp = await c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["db"] is True
