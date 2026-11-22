from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_defaults(authed: AsyncClient) -> None:
    resp = await authed.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["leader_mm"], body["frame_pitch_mm"], body["timezone"]) == (
        250,
        38,
        "Europe/London",
    )


async def test_patch_changes_only_what_is_sent(authed: AsyncClient) -> None:
    resp = await authed.patch("/api/settings", json={"leader_mm": 300})
    assert resp.status_code == 200
    assert resp.json()["leader_mm"] == 300
    assert resp.json()["frame_pitch_mm"] == 38
    again = (await authed.get("/api/settings")).json()
    assert (again["leader_mm"], again["frame_pitch_mm"]) == (300, 38)

    both = await authed.patch(
        "/api/settings", json={"frame_pitch_mm": 40, "timezone": "America/New_York"}
    )
    assert (both.json()["frame_pitch_mm"], both.json()["timezone"]) == (40, "America/New_York")


@pytest.mark.parametrize(
    "body",
    [
        {"leader_mm": 0},
        {"leader_mm": -5},
        {"frame_pitch_mm": 0},
        {"frame_pitch_mm": -38},
        {"leader_mm": 1.5},
        {"leader_mm": "lots"},
        {"leader_mm": None},
        {"leader_mm": 10_001},
        {"frame_pitch_mm": 1_001},
        {"timezone": ""},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "../../etc/passwd"},
        {"timezone": None},
        {"colour": "red"},
    ],
)
async def test_invalid_values_rejected_and_nothing_changes(
    authed: AsyncClient, body: dict[str, object]
) -> None:
    resp = await authed.patch("/api/settings", json=body)
    assert resp.status_code == 422, body
    now = (await authed.get("/api/settings")).json()
    assert (now["leader_mm"], now["frame_pitch_mm"], now["timezone"]) == (250, 38, "Europe/London")


async def test_attribution_recorded(authed: AsyncClient, engine: AsyncEngine) -> None:
    await authed.patch("/api/settings", json={"leader_mm": 260})
    async with engine.connect() as conn:
        row = (await conn.execute(text("select updated_by from settings"))).one()
        user = (await conn.execute(text("select id from users"))).scalar_one()
    assert row.updated_by == user


async def test_still_a_single_row(authed: AsyncClient, engine: AsyncEngine) -> None:
    await authed.patch("/api/settings", json={"leader_mm": 260})
    async with engine.connect() as conn:
        assert (await conn.execute(text("select count(*) from settings"))).scalar_one() == 1


async def test_scopes(
    authed: AsyncClient, bearer_client: Callable[..., Awaitable[AsyncClient]]
) -> None:
    reader = await bearer_client("films:read")
    writer = await bearer_client("films:write")
    async with reader, writer:
        assert (await reader.get("/api/settings")).status_code == 200
        denied = await reader.patch("/api/settings", json={"leader_mm": 300})
        assert denied.status_code == 403
        assert (await writer.patch("/api/settings", json={"leader_mm": 300})).status_code == 200


async def test_unauthenticated_401(client: AsyncClient) -> None:
    assert (await client.get("/api/settings")).status_code == 401
    assert (await client.patch("/api/settings", json={"leader_mm": 300})).status_code == 401
