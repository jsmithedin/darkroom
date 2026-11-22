import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def spool(g: dict[str, str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"label": "Bulk 1", "film_id": g["film"], "length_mm": 17_000}
    return body | over


async def create(authed: AsyncClient, g: dict[str, str], **over: Any) -> dict[str, Any]:
    resp = await authed.post("/api/bulk-rolls", json=spool(g, **over))
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def load(
    authed: AsyncClient, bulk_id: str, rolls: int, exposures: int = 36
) -> dict[str, Any]:
    resp = await authed.post(
        "/api/stock-movements",
        json={
            "kind": "bulk_load",
            "bulk_roll_id": bulk_id,
            "occurred_on": "2026-11-06",
            "rolls": rolls,
            "exposures_per_cassette": exposures,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def test_bulk_1_matches_sheet(authed: AsyncClient, gear: dict[str, str]) -> None:
    gear_film = gear["film"]
    created = await create(authed, gear, film_id=gear_film, used_before_mm=9_700)
    assert created["left_mm"] == 7_300
    assert created["exposures_left"] == 185
    assert created["used_mm"] == 9_700
    assert created["cassettes_loaded"] == 0
    assert created["cost_per_36_pence"] is None  # date, cost and supplier all optional
    assert (created["cost_pence"], created["supplier"], created["bought_on"]) == (None, None, None)
    assert created["film"]["name"] == "Tri-X"
    assert created["finished"] is False


async def test_loads_reduce_left_using_snapshot_metres(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bulk = await create(authed, gear, used_before_mm=9_700)
    await load(authed, bulk["id"], rolls=2)  # 2 x 1618 = 3236
    spool_now = (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).json()
    assert spool_now["cassettes_loaded"] == 2
    assert spool_now["used_mm"] == 9_700 + 3_236
    assert spool_now["left_mm"] == 4_064
    assert spool_now["exposures_left"] == 100  # (4064 - 250) // 38

    # a settings change leaves the snapshot alone but changes the live exposure count
    await authed.patch("/api/settings", json={"leader_mm": 300})
    later = (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).json()
    assert later["used_mm"] == 9_700 + 3_236
    assert later["left_mm"] == 4_064
    assert later["exposures_left"] == 99  # (4064 - 300) // 38


async def test_several_loads_add_up(authed: AsyncClient, gear: dict[str, str]) -> None:
    bulk = await create(authed, gear)
    await load(authed, bulk["id"], rolls=1, exposures=36)  # 1618
    await load(authed, bulk["id"], rolls=3, exposures=24)  # 3 x 1162 = 3486
    got = (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).json()
    assert got["cassettes_loaded"] == 4
    assert got["used_mm"] == 1_618 + 3_486


async def test_unpriced_spool_allowed_and_priced_spool_costs_per_36(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    unpriced = await create(authed, gear, label="Unpriced")
    assert unpriced["cost_per_36_pence"] is None
    priced = await create(authed, gear, label="Priced", cost_pence=1_700, supplier="Foma")
    assert priced["cost_per_36_pence"] == 162
    assert priced["supplier"] == "Foma"
    free = await create(authed, gear, label="Free", cost_pence=0)
    assert free["cost_per_36_pence"] == 0


async def test_overdrawn_spool_exposures_floor_at_zero(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bulk = await create(authed, gear, length_mm=2_000)
    await load(authed, bulk["id"], rolls=2)  # needs 3236 from a 2000 mm spool: allowed
    got = (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).json()
    assert got["left_mm"] == 2_000 - 3_236
    assert got["left_mm"] < 0
    assert got["exposures_left"] == 0


async def test_delete_with_loads_409(authed: AsyncClient, gear: dict[str, str]) -> None:
    bulk = await create(authed, gear)
    movement = await load(authed, bulk["id"], rolls=1)
    refused = await authed.delete(f"/api/bulk-rolls/{bulk['id']}")
    assert refused.status_code == 409
    assert "Bulk 1" in refused.json()["detail"]
    assert (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).status_code == 200
    assert movement["bulk_roll_id"] == bulk["id"]


async def test_delete_without_loads(authed: AsyncClient, gear: dict[str, str]) -> None:
    bulk = await create(authed, gear)
    assert (await authed.delete(f"/api/bulk-rolls/{bulk['id']}")).status_code == 204
    assert (await authed.get(f"/api/bulk-rolls/{bulk['id']}")).status_code == 404
    assert (await authed.delete(f"/api/bulk-rolls/{bulk['id']}")).status_code == 404


async def test_delete_after_removing_the_loads(authed: AsyncClient, gear: dict[str, str]) -> None:
    # stock the loads add must not be needed by any roll for the load to be deletable
    bulk = await create(authed, gear)
    movement = await load(authed, bulk["id"], rolls=1)
    assert (await authed.delete(f"/api/stock-movements/{movement['id']}")).status_code == 204
    assert (await authed.delete(f"/api/bulk-rolls/{bulk['id']}")).status_code == 204


async def test_label_unique_case_insensitive(authed: AsyncClient, gear: dict[str, str]) -> None:
    first = await create(authed, gear, label="Bulk 1")
    for label in ("Bulk 1", "bulk 1", "  BULK 1  "):
        resp = await authed.post("/api/bulk-rolls", json=spool(gear, label=label))
        assert resp.status_code == 409, label
        assert "already exists" in resp.json()["detail"]
    second = await create(authed, gear, label="Bulk 2")
    clash = await authed.patch(f"/api/bulk-rolls/{second['id']}", json={"label": "BULK 1"})
    assert clash.status_code == 409
    same = await authed.patch(f"/api/bulk-rolls/{first['id']}", json={"label": "BULK 1"})
    assert same.status_code == 200  # recasing its own label is fine


@pytest.mark.parametrize(
    "over",
    [
        {"length_mm": 0},
        {"length_mm": -5},
        {"length_mm": 1.5},
        {"cost_pence": -1},
        {"cost_pence": 12.5},
        {"used_before_mm": -1},
        {"label": ""},
        {"label": "   "},
        {"film_id": "nope"},
        {"bought_on": "yesterday"},
        {"colour": "red"},
    ],
)
async def test_validation(authed: AsyncClient, gear: dict[str, str], over: dict[str, Any]) -> None:
    resp = await authed.post("/api/bulk-rolls", json=spool(gear, **over))
    assert resp.status_code == 422, over


async def test_unknown_film_422(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.post("/api/bulk-rolls", json=spool(gear, film_id=str(uuid.uuid4())))
    assert resp.status_code == 422
    assert "Unknown film" in resp.json()["detail"]


async def test_patch_updates_and_clears(authed: AsyncClient, gear: dict[str, str]) -> None:
    bulk = await create(authed, gear, cost_pence=1_700, supplier="Foma", notes="first")
    url = f"/api/bulk-rolls/{bulk['id']}"
    resp = await authed.patch(
        url, json={"cost_pence": None, "supplier": None, "finished": True, "used_before_mm": 500}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cost_pence"] is None
    assert body["cost_per_36_pence"] is None
    assert body["supplier"] is None
    assert body["finished"] is True
    assert body["notes"] == "first"  # untouched
    assert body["left_mm"] == 16_500


@pytest.mark.parametrize("field", ["label", "film_id", "length_mm", "used_before_mm", "finished"])
async def test_patch_cannot_null_required_fields(
    authed: AsyncClient, gear: dict[str, str], field: str
) -> None:
    bulk = await create(authed, gear)
    resp = await authed.patch(f"/api/bulk-rolls/{bulk['id']}", json={field: None})
    assert resp.status_code == 422


async def test_film_can_change_only_before_any_load(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bulk = await create(authed, gear)
    url = f"/api/bulk-rolls/{bulk['id']}"
    ok = await authed.patch(url, json={"film_id": gear["film2"]})
    assert ok.status_code == 200
    assert ok.json()["film"]["name"] == "Portra"
    await load(authed, bulk["id"], rolls=1)
    refused = await authed.patch(url, json={"film_id": gear["film"]})
    assert refused.status_code == 409
    assert "cannot change" in refused.json()["detail"]
    # sending the film it already has is not a change
    same = await authed.patch(url, json={"film_id": gear["film2"], "notes": "x"})
    assert same.status_code == 200


async def test_list_orders_unfinished_first_and_can_hide_finished(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await create(authed, gear, label="B", finished=True)
    await create(authed, gear, label="C")
    await create(authed, gear, label="A")
    labels = [b["label"] for b in (await authed.get("/api/bulk-rolls")).json()]
    assert labels == ["A", "C", "B"]
    active = (await authed.get("/api/bulk-rolls", params={"include_finished": "false"})).json()
    assert [b["label"] for b in active] == ["A", "C"]


async def test_list_derives_figures_for_every_spool(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    a = await create(authed, gear, label="A", used_before_mm=9_700)
    await create(authed, gear, label="B", length_mm=30_480, cost_pence=3_000)
    await load(authed, a["id"], rolls=1)
    by_label = {s["label"]: s for s in (await authed.get("/api/bulk-rolls")).json()}
    assert by_label["A"]["cassettes_loaded"] == 1
    assert by_label["A"]["left_mm"] == 17_000 - 9_700 - 1_618
    assert by_label["B"]["cassettes_loaded"] == 0
    assert by_label["B"]["cost_per_36_pence"] == 159  # 3000p for 30.48 m


async def test_unknown_id_404(authed: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await authed.get(f"/api/bulk-rolls/{missing}")).status_code == 404
    assert (
        await authed.patch(f"/api/bulk-rolls/{missing}", json={"notes": "x"})
    ).status_code == 404


async def test_attribution_recorded(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    await create(authed, gear)
    async with engine.connect() as conn:
        row = (await conn.execute(text("select created_by, updated_by from bulk_rolls"))).one()
        user = (await conn.execute(text("select id from users"))).scalar_one()
    assert row.created_by == user == row.updated_by


async def test_scopes(
    authed: AsyncClient,
    gear: dict[str, str],
    bearer_client: Callable[..., Awaitable[AsyncClient]],
) -> None:
    bulk = await create(authed, gear)
    reader = await bearer_client("films:read")
    async with reader:
        assert (await reader.get("/api/bulk-rolls")).status_code == 200
        assert (await reader.get(f"/api/bulk-rolls/{bulk['id']}")).status_code == 200
        assert (
            await reader.post("/api/bulk-rolls", json=spool(gear, label="X"))
        ).status_code == 403
        url = f"/api/bulk-rolls/{bulk['id']}"
        assert (await reader.patch(url, json={"notes": "x"})).status_code == 403
        assert (await reader.delete(url)).status_code == 403


async def test_unauthenticated_401(client: AsyncClient) -> None:
    assert (await client.get("/api/bulk-rolls")).status_code == 401
