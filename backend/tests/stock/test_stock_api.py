import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import BulkRoll
from tests.support import roll_body


def purchase(g: dict[str, str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "purchase",
        "film_id": g["film"],
        "format_id": g["format35"],
        "occurred_on": "2026-11-01",
        "rolls": 5,
        "cost_pence": 2500,
        "supplier": "Analogue Wonderland",
    }
    return body | over


async def post(authed: AsyncClient, body: dict[str, Any], expect: int = 201) -> dict[str, Any]:
    resp = await authed.post("/api/stock-movements", json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def stock(authed: AsyncClient, **params: Any) -> dict[tuple[str, str], int]:
    rows = (await authed.get("/api/stock", params=params)).json()
    return {(r["film"]["name"], r["format"]["name"]): r["rolls"] for r in rows}


async def make_bulk(engine: AsyncEngine, film_id: str, **over: Any) -> uuid.UUID:
    async with AsyncSession(engine) as s:
        bulk = BulkRoll(label=f"Bulk {uuid.uuid4()}", film_id=uuid.UUID(film_id), length_mm=17_000)
        for k, v in over.items():
            setattr(bulk, k, v)
        s.add(bulk)
        await s.flush()
        bulk_id = bulk.id
        await s.commit()
        return bulk_id


# --- recording movements ---------------------------------------------------------------


async def test_purchase_recorded(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await post(authed, purchase(gear))
    assert created["kind"] == "purchase"
    assert created["rolls"] == 5
    assert created["cost_pence"] == 2500
    assert created["film"]["name"] == "Tri-X"
    assert created["format"]["name"] == "35mm"
    assert await stock(authed) == {("Tri-X", "35mm"): 5}


@pytest.mark.parametrize(
    "over",
    [
        {"cost_pence": None},
        {"cost_pence": -1},
        {"cost_pence": 12.5},
        {"rolls": 0},
        {"rolls": -3},
        {"exposures_per_cassette": 36},
        {"metres_mm": 100},
        {"counted_to": 5},
        {"film_id": "nope"},
    ],
)
async def test_bad_purchases_rejected(
    authed: AsyncClient, gear: dict[str, str], over: dict[str, Any]
) -> None:
    body = purchase(gear) | over
    if over.get("cost_pence", 0) is None:
        del body["cost_pence"]
    await post(authed, body, expect=422)
    assert await stock(authed) == {}


async def test_unknown_film_or_format_rejected(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.post("/api/stock-movements", json=purchase(gear, film_id=str(uuid.uuid4())))
    assert resp.status_code == 422
    assert "Unknown film" in resp.json()["detail"]
    resp = await authed.post(
        "/api/stock-movements", json=purchase(gear, format_id=str(uuid.uuid4()))
    )
    assert "Unknown format" in resp.json()["detail"]


async def test_given_away(authed: AsyncClient, gear: dict[str, str]) -> None:
    await post(authed, purchase(gear))
    body = {
        "kind": "given_away",
        "film_id": gear["film"],
        "format_id": gear["format35"],
        "occurred_on": "2026-11-02",
        "rolls": -2,
    }
    created = await post(authed, body)
    assert created["rolls"] == -2
    assert await stock(authed) == {("Tri-X", "35mm"): 3}
    await post(authed, body | {"rolls": 2}, expect=422)  # positive is not "given away"
    await post(authed, body | {"rolls": 0}, expect=422)


async def test_opening(authed: AsyncClient, gear: dict[str, str]) -> None:
    body = {
        "kind": "opening",
        "film_id": gear["film"],
        "format_id": gear["format120"],
        "occurred_on": "2026-11-22",
        "rolls": 12,
    }
    await post(authed, body)
    assert await stock(authed) == {("Tri-X", "120"): 12}
    await post(authed, body | {"rolls": -1}, expect=422)  # opening_negative_rejected
    await post(authed, body | {"rolls": 0}, expect=422)


async def test_unknown_kind_and_extra_fields_rejected(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, kind="gift"), expect=422)
    await post(authed, {"kind": "adjustment", "film_id": gear["film"]}, expect=422)


# --- the stock figure ------------------------------------------------------------------


async def test_stock_is_movements_minus_counted_rolls(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=10))
    await post(authed, purchase(gear, rolls=5, format_id=gear["format120"]))
    for _ in range(3):
        assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 201
    assert await stock(authed) == {("Tri-X", "35mm"): 7, ("Tri-X", "120"): 5}


async def test_rolls_with_flag_off_do_not_reduce_stock(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=10))
    await authed.post("/api/rolls", json=roll_body(gear, counts_against_stock=False))
    await authed.post("/api/rolls", json=roll_body(gear, counts_against_stock=False))
    assert await stock(authed) == {("Tri-X", "35mm"): 10}
    await authed.post("/api/rolls", json=roll_body(gear))
    assert await stock(authed) == {("Tri-X", "35mm"): 9}


async def test_rolls_of_other_film_or_format_do_not_affect_stock(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=10))
    await authed.post("/api/rolls", json=roll_body(gear, format_id=gear["format120"]))
    assert (await stock(authed))[("Tri-X", "35mm")] == 10


async def test_stock_grouped_by_type_and_zero_rows_hidden_by_default(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, film_id=gear["film2"], rolls=2))  # Portra (colour)
    await post(authed, purchase(gear, rolls=4))  # Tri-X (bw)
    await post(authed, purchase(gear, rolls=1, format_id=gear["format120"]))
    await post(
        authed,
        {
            "kind": "given_away",
            "film_id": gear["film"],
            "format_id": gear["format120"],
            "occurred_on": "2026-11-03",
            "rolls": -1,
        },
    )
    rows = (await authed.get("/api/stock")).json()
    assert [(r["film"]["type"], r["film"]["name"], r["format"]["name"]) for r in rows] == [
        ("bw", "Tri-X", "35mm"),
        ("colour", "Portra", "35mm"),
    ]
    with_zero = (await authed.get("/api/stock", params={"include_zero": "true"})).json()
    assert len(with_zero) == 3
    assert any(r["rolls"] == 0 and r["format"]["name"] == "120" for r in with_zero)


# --- adjustments -----------------------------------------------------------------------


async def test_adjustment_records_delta_and_counted_to(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=3))
    body = {
        "film_id": gear["film"],
        "format_id": gear["format35"],
        "counted": 10,
        "occurred_on": "2026-11-05",
        "notes": "Recount",
    }
    up = (await authed.post("/api/stock-adjustments", json=body)).json()
    assert up["kind"] == "adjustment"
    assert up["rolls"] == 7
    assert up["counted_to"] == 10
    assert await stock(authed) == {("Tri-X", "35mm"): 10}

    down = (await authed.post("/api/stock-adjustments", json=body | {"counted": 4})).json()
    assert (down["rolls"], down["counted_to"]) == (-6, 4)
    assert await stock(authed) == {("Tri-X", "35mm"): 4}

    to_zero = (await authed.post("/api/stock-adjustments", json=body | {"counted": 0})).json()
    assert to_zero["rolls"] == -4
    assert await stock(authed) == {}


async def test_adjustment_from_nothing_and_no_change(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    body = {
        "film_id": gear["film"],
        "format_id": gear["format35"],
        "counted": 6,
        "occurred_on": "2026-11-05",
    }
    first = (await authed.post("/api/stock-adjustments", json=body)).json()
    assert first["rolls"] == 6
    same = await authed.post("/api/stock-adjustments", json=body)
    assert same.status_code == 422
    assert "nothing to adjust" in same.json()["detail"]
    assert (
        await authed.post("/api/stock-adjustments", json=body | {"counted": -1})
    ).status_code == 422


async def test_adjustment_accounts_for_counted_rolls(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=5))
    await authed.post("/api/rolls", json=roll_body(gear))  # stock is now 4
    resp = await authed.post(
        "/api/stock-adjustments",
        json={
            "film_id": gear["film"],
            "format_id": gear["format35"],
            "counted": 4,
            "occurred_on": "2026-11-05",
        },
    )
    assert resp.status_code == 422  # already 4


# --- bulk loads ------------------------------------------------------------------------


async def test_bulk_load_snapshots_metres_and_survives_settings_change(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    bulk = await make_bulk(engine, gear["film"])
    body = {
        "kind": "bulk_load",
        "bulk_roll_id": str(bulk),
        "occurred_on": "2026-11-06",
        "rolls": 2,
        "exposures_per_cassette": 36,
    }
    created = await post(authed, body)
    assert created["metres_mm"] == 2 * 1618
    assert created["rolls"] == 2
    assert created["film"]["name"] == "Tri-X"  # from the spool
    assert created["format"]["name"] == "35mm"  # always 35mm
    assert created["bulk_roll_id"] == str(bulk)
    assert await stock(authed) == {("Tri-X", "35mm"): 2}

    # a settings change does not rewrite history, only later loads
    assert (await authed.patch("/api/settings", json={"leader_mm": 300})).status_code == 200
    listed = (await authed.get("/api/stock-movements", params={"kind": "bulk_load"})).json()
    assert listed["items"][0]["metres_mm"] == 3236
    later = await post(authed, body | {"rolls": 1, "exposures_per_cassette": 24})
    assert later["metres_mm"] == 300 + 24 * 38


async def test_bulk_load_larger_than_the_spool_is_allowed(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    bulk = await make_bulk(engine, gear["film"], length_mm=1_000)
    body = {
        "kind": "bulk_load",
        "bulk_roll_id": str(bulk),
        "occurred_on": "2026-11-06",
        "rolls": 3,
        "exposures_per_cassette": 36,
    }
    assert (await authed.post("/api/stock-movements", json=body)).status_code == 201


async def test_bulk_load_validation(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    bulk = await make_bulk(engine, gear["film"])
    ok = {
        "kind": "bulk_load",
        "bulk_roll_id": str(bulk),
        "occurred_on": "2026-11-06",
        "rolls": 1,
        "exposures_per_cassette": 36,
    }
    unknown = await authed.post(
        "/api/stock-movements", json=ok | {"bulk_roll_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 422
    assert "Unknown bulk roll" in unknown.json()["detail"]
    for over in [
        {"exposures_per_cassette": 0},
        {"rolls": 0},
        {"rolls": -1},
        {"film_id": gear["film2"]},  # film comes from the spool
        {"format_id": gear["format120"]},  # and the format is always 35mm
        {"cost_pence": 5},
    ]:
        await post(authed, ok | over, expect=422)


async def test_bulk_load_needs_a_35mm_format(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    bulk = await make_bulk(engine, gear["film"])
    async with engine.begin() as conn:
        await conn.execute(text("update formats set name = 'thirty-five' where name = '35mm'"))
    try:
        resp = await authed.post(
            "/api/stock-movements",
            json={
                "kind": "bulk_load",
                "bulk_roll_id": str(bulk),
                "occurred_on": "2026-11-06",
                "rolls": 1,
                "exposures_per_cassette": 36,
            },
        )
        assert resp.status_code == 422
        assert "35mm" in resp.json()["detail"]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("update formats set name = '35mm' where name = 'thirty-five'"))


# --- listing, editing, deleting --------------------------------------------------------


async def test_list_filters_and_pagination(authed: AsyncClient, gear: dict[str, str]) -> None:
    a = await post(authed, purchase(gear, occurred_on="2026-01-05"))
    b = await post(authed, purchase(gear, occurred_on="2026-02-05", film_id=gear["film2"]))
    c = await post(authed, purchase(gear, occurred_on="2026-03-05", format_id=gear["format120"]))

    async def ids(**params: Any) -> list[str]:
        resp = await authed.get("/api/stock-movements", params=params)
        assert resp.status_code == 200
        return [m["id"] for m in resp.json()["items"]]

    assert await ids() == [c["id"], b["id"], a["id"]]
    assert await ids(film=gear["film2"]) == [b["id"]]
    assert await ids(format=gear["format120"]) == [c["id"]]
    assert await ids(kind="purchase") == [c["id"], b["id"], a["id"]]
    assert await ids(kind="opening") == []
    assert await ids(**{"from": "2026-02-01", "to": "2026-02-28"}) == [b["id"]]
    page = (await authed.get("/api/stock-movements", params={"limit": 1, "offset": 1})).json()
    assert [m["id"] for m in page["items"]] == [b["id"]]
    assert page["total"] == 3
    assert (await authed.get("/api/stock-movements", params={"kind": "gift"})).status_code == 422


async def test_patch_purchase(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await post(authed, purchase(gear))
    resp = await authed.patch(
        f"/api/stock-movements/{created['id']}",
        json={"rolls": 8, "cost_pence": 4000, "supplier": None, "notes": "fixed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["rolls"], body["cost_pence"], body["supplier"], body["notes"]) == (
        8,
        4000,
        None,
        "fixed",
    )
    assert await stock(authed) == {("Tri-X", "35mm"): 8}
    moved = await authed.patch(
        f"/api/stock-movements/{created['id']}", json={"format_id": gear["format120"]}
    )
    assert moved.json()["format"]["name"] == "120"


async def test_patch_cannot_break_the_kind(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await post(authed, purchase(gear))
    url = f"/api/stock-movements/{created['id']}"
    assert (await authed.patch(url, json={"rolls": -2})).status_code == 422  # CHECK catches it
    assert (await authed.patch(url, json={"rolls": 0})).status_code == 422
    assert (await authed.patch(url, json={"rolls": None})).status_code == 422
    assert (await authed.patch(url, json={"exposures_per_cassette": 36})).status_code == 422
    assert (await authed.patch(url, json={"kind": "opening"})).status_code == 422
    assert (await authed.patch(url, json={"film_id": str(uuid.uuid4())})).status_code == 422
    assert await stock(authed) == {("Tri-X", "35mm"): 5}  # untouched


async def test_adjustment_only_date_and_notes_editable(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    adj = (
        await authed.post(
            "/api/stock-adjustments",
            json={
                "film_id": gear["film"],
                "format_id": gear["format35"],
                "counted": 6,
                "occurred_on": "2026-11-05",
            },
        )
    ).json()
    url = f"/api/stock-movements/{adj['id']}"
    assert (await authed.patch(url, json={"rolls": 9})).status_code == 422
    ok = await authed.patch(url, json={"notes": "after the move", "occurred_on": "2026-11-04"})
    assert ok.status_code == 200
    assert ok.json()["occurred_on"] == "2026-11-04"


async def test_editing_a_bulk_load_recomputes_metres(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    bulk = await make_bulk(engine, gear["film"])
    load = await post(
        authed,
        {
            "kind": "bulk_load",
            "bulk_roll_id": str(bulk),
            "occurred_on": "2026-11-06",
            "rolls": 2,
            "exposures_per_cassette": 36,
        },
    )
    resp = await authed.patch(
        f"/api/stock-movements/{load['id']}", json={"rolls": 3, "exposures_per_cassette": 24}
    )
    assert resp.json()["metres_mm"] == 3 * (250 + 24 * 38)
    assert resp.json()["rolls"] == 3
    assert (
        await authed.patch(f"/api/stock-movements/{load['id']}", json={"film_id": gear["film2"]})
    ).status_code == 422


async def test_delete_movement(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await post(authed, purchase(gear))
    assert (await authed.delete(f"/api/stock-movements/{created['id']}")).status_code == 204
    assert await stock(authed) == {}
    assert (await authed.delete(f"/api/stock-movements/{created['id']}")).status_code == 404
    missing = uuid.uuid4()
    assert (
        await authed.patch(f"/api/stock-movements/{missing}", json={"notes": "x"})
    ).status_code == 404


async def test_attribution_recorded(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    await post(authed, purchase(gear))
    async with engine.connect() as conn:
        row = (await conn.execute(text("select created_by, updated_by from stock_movements"))).one()
        user = (await conn.execute(text("select id from users"))).scalar_one()
    assert row.created_by == user == row.updated_by


# --- access ----------------------------------------------------------------------------


async def test_scopes(
    authed: AsyncClient,
    gear: dict[str, str],
    bearer_client: Callable[..., Awaitable[AsyncClient]],
) -> None:
    created = await post(authed, purchase(gear))
    reader = await bearer_client("films:read")
    async with reader:
        assert (await reader.get("/api/stock")).status_code == 200
        assert (await reader.get("/api/stock-movements")).status_code == 200
        assert (await reader.post("/api/stock-movements", json=purchase(gear))).status_code == 403
        adjustment = {
            "film_id": gear["film"],
            "format_id": gear["format35"],
            "counted": 1,
            "occurred_on": "2026-11-05",
        }
        assert (await reader.post("/api/stock-adjustments", json=adjustment)).status_code == 403
        url = f"/api/stock-movements/{created['id']}"
        assert (await reader.patch(url, json={"notes": "x"})).status_code == 403
        assert (await reader.delete(url)).status_code == 403


async def test_unauthenticated_401(client: AsyncClient) -> None:
    for path in ["/api/stock", "/api/stock-movements"]:
        assert (await client.get(path)).status_code == 401
