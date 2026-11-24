from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient

from tests.mcp.conftest import McpEnv, call_tool, list_tools, seed

Session = Callable[[str], Awaitable[AsyncClient]]

WRITE_TOOLS = {
    "log_roll": {
        "dev_date": "2026-11-12",
        "camera": "Nikon FM2",
        "film": "Tri-X",
        "ei": 400,
        "developer": "HC-110",
    },
    "update_roll": {"roll_id": "00000000-0000-0000-0000-000000000000", "notes": "x"},
    "record_purchase": {
        "film": "Tri-X",
        "occurred_on": "2026-11-12",
        "rolls": 2,
        "cost_pence": 900,
    },
    "record_bulk_load": {"bulk_roll": "Bulk 1", "occurred_on": "2026-11-12", "rolls": 1},
    "record_given_away": {"film": "Tri-X", "occurred_on": "2026-11-12", "rolls": 1},
    "record_stock_adjustment": {"film": "Tri-X", "counted": 1, "occurred_on": "2026-11-12"},
    "create_bulk_roll": {"label": "Bulk 2", "film": "Tri-X", "length_mm": 30000},
    "update_bulk_roll": {"bulk_roll": "Bulk 1", "notes": "x"},
    "add_reference_item": {"kind": "lenses", "name": "85mm"},
}


@pytest.fixture
async def env(mcp_env: McpEnv) -> McpEnv:
    await seed(mcp_env)
    return mcp_env


async def audit_events(env: McpEnv) -> list[dict[str, Any]]:
    async with env.client(await env.pat("films:read")) as c:
        resp = await c.get("/api/audit-events")
        assert resp.status_code == 200
        return resp.json()["items"]  # type: ignore[no-any-return]


async def test_write_tools_listed_with_descriptions(env: McpEnv, mcp_session: Session) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        tools = {t["name"]: t for t in await list_tools(session)}
    finally:
        await session.aclose()
    assert set(WRITE_TOOLS) <= set(tools)
    assert all(tools[name]["description"].strip() for name in WRITE_TOOLS)


@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
async def test_every_write_tool_refuses_read_only_token(
    env: McpEnv, mcp_session: Session, tool: str
) -> None:
    session = await mcp_session(await env.pat("films:read"))
    try:
        result = await call_tool(session, tool, WRITE_TOOLS[tool])
    finally:
        await session.aclose()
    assert result["isError"] is True
    assert "films:write" in result["content"][0]["text"]
    assert await audit_events(env) == []


async def test_write_tool_creates_audit_event_with_token_id(
    env: McpEnv, mcp_session: Session
) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        result = await call_tool(session, "log_roll", WRITE_TOOLS["log_roll"])
    finally:
        await session.aclose()
    assert not result.get("isError"), result
    roll = result["structuredContent"]
    assert roll["film"]["name"] == "Tri-X"
    [event] = await audit_events(env)
    assert event["tool"] == "log_roll"
    assert event["entity_type"] == "roll"
    assert event["entity_id"] == roll["id"]
    assert event["via"] == "pat"
    assert event["token_id"] is not None
    assert event["actor"] == "t"
    assert event["client_id"] is None


async def test_write_tool_creates_audit_event_with_client_id_for_oauth(
    env: McpEnv, mcp_session: Session
) -> None:
    session = await mcp_session(await env.oauth_token("films:write"))
    try:
        result = await call_tool(session, "add_reference_item", {"kind": "lenses", "name": "85mm"})
    finally:
        await session.aclose()
    assert not result.get("isError"), result
    [event] = await audit_events(env)
    assert event["via"] == "oauth"
    assert event["client_id"] == "claude"
    assert event["actor"] == "Claude"
    assert event["entity_type"] == "lenses"


async def test_failed_write_creates_no_audit_event(env: McpEnv, mcp_session: Session) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        result = await call_tool(
            session, "record_given_away", WRITE_TOOLS["record_given_away"] | {"rolls": 99}
        )
    finally:
        await session.aclose()
    assert result["isError"] is True
    assert await audit_events(env) == []


async def test_log_roll_without_stock_returns_tool_error_naming_film(
    env: McpEnv, mcp_session: Session
) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        body = WRITE_TOOLS["log_roll"] | {"format": "120"}
        result = await call_tool(session, "log_roll", body)
    finally:
        await session.aclose()
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "Tri-X" in text
    assert "120" in text
    assert await audit_events(env) == []


async def test_unknown_name_is_a_tool_error(env: McpEnv, mcp_session: Session) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        result = await call_tool(session, "log_roll", WRITE_TOOLS["log_roll"] | {"camera": "Leica"})
    finally:
        await session.aclose()
    assert result["isError"] is True
    assert "Leica" in result["content"][0]["text"]


async def test_stock_and_bulk_tools_work_end_to_end(env: McpEnv, mcp_session: Session) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        purchase = await call_tool(session, "record_purchase", WRITE_TOOLS["record_purchase"])
        assert purchase["structuredContent"]["rolls"] == 2
        load = await call_tool(session, "record_bulk_load", WRITE_TOOLS["record_bulk_load"])
        assert not load.get("isError"), load
        given = await call_tool(session, "record_given_away", WRITE_TOOLS["record_given_away"])
        assert given["structuredContent"]["rolls"] == -1
        adj = await call_tool(
            session, "record_stock_adjustment", WRITE_TOOLS["record_stock_adjustment"]
        )
        assert adj["structuredContent"]["kind"] == "adjustment"
        spool = await call_tool(session, "create_bulk_roll", WRITE_TOOLS["create_bulk_roll"])
        assert spool["structuredContent"]["label"] == "Bulk 2"
        done = await call_tool(
            session, "update_bulk_roll", {"bulk_roll": "Bulk 2", "finished": True}
        )
        assert done["structuredContent"]["finished"] is True
        roll_id = (await call_tool(session, "log_roll", WRITE_TOOLS["log_roll"]))[
            "structuredContent"
        ]["id"]
        edited = await call_tool(
            session, "update_roll", {"roll_id": roll_id, "subject": "Docks", "lens": "none"}
        )
        assert edited["structuredContent"]["subject"] == "Docks"
        assert edited["structuredContent"]["lens"] is None
    finally:
        await session.aclose()
    assert len(await audit_events(env)) == 8


async def test_no_delete_tools_registered(env: McpEnv, mcp_session: Session) -> None:
    session = await mcp_session(await env.pat("films:write"))
    try:
        names = [t["name"] for t in await list_tools(session)]
    finally:
        await session.aclose()
    assert not [n for n in names if n.startswith("delete")]
