from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient

from tests.mcp.conftest import McpEnv, call_tool, list_tools, seed

Session = Callable[[str], Awaitable[AsyncClient]]

READ_TOOLS = {
    "list_rolls",
    "get_stock",
    "get_bulk_rolls",
    "get_stats",
    "get_dev_times",
    "list_reference_data",
    "get_low_stock",
    "get_camera_idle",
    "get_spend",
}


@pytest.fixture
async def reader(mcp_env: McpEnv, mcp_session: Session) -> Any:
    g = await seed(mcp_env)
    rest = mcp_env.client(await mcp_env.pat("films:read"))
    session = await mcp_session(await mcp_env.pat("films:read"))
    yield session, rest, g
    await session.aclose()
    await rest.aclose()


async def test_read_tools_listed_with_descriptions(reader: Any) -> None:
    session, _, _ = reader
    tools = {t["name"]: t for t in await list_tools(session)}
    assert set(tools) >= READ_TOOLS
    for name in READ_TOOLS:
        assert tools[name]["description"].strip(), name
        assert tools[name]["inputSchema"]["type"] == "object"


async def test_list_rolls_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "list_rolls", {"limit": 10})
    expected = (await rest.get("/api/rolls", params={"limit": 10})).json()
    assert result["structuredContent"] == expected
    assert expected["total"] == 2


async def test_list_rolls_filters_by_name(reader: Any) -> None:
    session, rest, g = reader
    result = await call_tool(session, "list_rolls", {"film": "tri-x", "q": "market"})
    expected = (await rest.get("/api/rolls", params={"film": g["film"], "q": "market"})).json()
    assert result["structuredContent"] == expected
    assert expected["total"] == 1
    unknown = await call_tool(session, "list_rolls", {"film": "Nonexistent"})
    assert unknown["isError"] is True
    assert "Nonexistent" in unknown["content"][0]["text"]


async def test_get_stock_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_stock")
    expected = (await rest.get("/api/stock")).json()
    assert result["structuredContent"]["result"] == expected
    assert expected[0]["rolls"] == 5


async def test_get_bulk_rolls_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_bulk_rolls")
    expected = (await rest.get("/api/bulk-rolls")).json()
    assert result["structuredContent"]["result"] == expected


async def test_get_stats_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_stats", {"year": 2026})
    assert result["structuredContent"] == (await rest.get("/api/stats?year=2026")).json()


async def test_get_dev_times_matches_rest(reader: Any) -> None:
    session, rest, g = reader
    result = await call_tool(session, "get_dev_times", {"film": "Tri-X", "ei": 800})
    expected = (await rest.get("/api/dev-times", params={"film": g["film"], "ei": 800})).json()
    assert result["structuredContent"]["result"] == expected
    assert expected


async def test_list_reference_data_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    for kind in ("films", "cameras", "formats"):
        result = await call_tool(session, "list_reference_data", {"kind": kind})
        assert result["structuredContent"]["result"] == (await rest.get(f"/api/{kind}")).json()


async def test_get_low_stock_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_low_stock")
    assert result["structuredContent"]["result"] == (await rest.get("/api/stats/low-stock")).json()


async def test_get_camera_idle_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_camera_idle")
    expected = (await rest.get("/api/stats/camera-idle")).json()
    assert result["structuredContent"]["result"] == expected
    assert expected[0]["name"] == "Nikon FM2"
    assert expected[0]["last_used"] == "2026-11-10"


async def test_get_spend_matches_rest(reader: Any) -> None:
    session, rest, _ = reader
    result = await call_tool(session, "get_spend")
    assert result["structuredContent"]["result"] == (await rest.get("/api/stats/spend")).json()
