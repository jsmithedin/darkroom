from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from tests.mcp.conftest import HEADERS, INIT, McpEnv, rpc_body


async def test_initialize_with_allowed_host(
    mcp_env: McpEnv, mcp_session: Callable[[str], Awaitable[AsyncClient]]
) -> None:
    c = await mcp_session(await mcp_env.pat())
    try:
        resp = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = rpc_body(resp)["result"]["tools"]
        assert [t["name"] for t in tools] == ["ping"]
    finally:
        await c.aclose()


async def test_wrong_host_rejected(mcp_env: McpEnv) -> None:
    token = await mcp_env.pat()
    async with AsyncClient(
        transport=mcp_env.client()._transport,  # type: ignore[attr-defined]
        base_url="https://evil.example",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        resp = await c.post("/mcp", headers=HEADERS, json=INIT)
        assert resp.status_code == 421


async def test_api_health_still_reachable(mcp_env: McpEnv) -> None:
    async with mcp_env.client() as c:
        resp = await c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["db"] is True
