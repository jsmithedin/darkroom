import asyncio
import uuid
from typing import Any

from httpx import AsyncClient

from tests.support import roll_body


async def purchase(
    authed: AsyncClient, g: dict[str, str], rolls: int, film: str = "film", fmt: str = "format35"
) -> dict[str, Any]:
    resp = await authed.post(
        "/api/stock-movements",
        json={
            "kind": "purchase",
            "film_id": g[film],
            "format_id": g[fmt],
            "occurred_on": "2026-11-01",
            "rolls": rolls,
            "cost_pence": 1000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def stock_of(authed: AsyncClient, film: str, fmt: str) -> int:
    rows = (await authed.get("/api/stock", params={"include_zero": "true"})).json()
    for r in rows:
        if (r["film"]["name"], r["format"]["name"]) == (film, fmt):
            return int(r["rolls"])
    return 0


def given_away(g: dict[str, str], rolls: int, film: str = "film", fmt: str = "format35"):  # type: ignore[no-untyped-def]
    return {
        "kind": "given_away",
        "film_id": g[film],
        "format_id": g[fmt],
        "occurred_on": "2026-11-02",
        "rolls": -rolls,
    }


async def test_roll_with_no_stock_409_with_names(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.post("/api/rolls", json=roll_body(gear))
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"] == "No Tri-X 35mm in stock. Record a purchase or a recount first."
    assert body["code"] == "insufficient_stock"
    assert (body["film"], body["format"], body["available"]) == ("Tri-X", "35mm", 0)
    assert body["film_id"] == gear["film"]
    assert body["format_id"] == gear["format35"]
    assert (await authed.get("/api/rolls")).json()["total"] == 0  # nothing was saved


async def test_message_says_how_many_are_held(authed: AsyncClient, gear: dict[str, str]) -> None:
    await purchase(authed, gear, 1)
    assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 201
    second = await authed.post("/api/rolls", json=roll_body(gear))
    assert second.status_code == 409
    assert second.json()["available"] == 0
    # a given-away of two when only one is left names the count
    await purchase(authed, gear, 1)
    too_many = await authed.post("/api/stock-movements", json=given_away(gear, 3))
    assert too_many.status_code == 409
    assert too_many.json()["available"] == 1
    assert "Only 1 Tri-X 35mm" in too_many.json()["detail"]


async def test_roll_uses_up_the_last_roll_then_fails(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 2)
    assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 201
    assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 201
    assert await stock_of(authed, "Tri-X", "35mm") == 0
    assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 409


async def test_flag_off_roll_ignores_stock(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.post("/api/rolls", json=roll_body(gear, counts_against_stock=False))
    assert resp.status_code == 201
    assert await stock_of(authed, "Tri-X", "35mm") == 0


async def test_editing_roll_to_other_film_checks_both_pairs(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)  # Tri-X 35mm
    created = (await authed.post("/api/rolls", json=roll_body(gear))).json()
    url = f"/api/rolls/{created['id']}"

    # Portra 35mm has none: moving the roll there is refused, and Tri-X is untouched
    refused = await authed.patch(url, json={"film_id": gear["film2"]})
    assert refused.status_code == 409
    assert "Portra" in refused.json()["detail"]
    assert await stock_of(authed, "Tri-X", "35mm") == 0
    assert (await authed.get(url)).json()["film"]["name"] == "Tri-X"

    # with Portra stocked it moves, giving the roll back to Tri-X
    await purchase(authed, gear, 1, film="film2")
    moved = await authed.patch(url, json={"film_id": gear["film2"]})
    assert moved.status_code == 200
    assert await stock_of(authed, "Tri-X", "35mm") == 1
    assert await stock_of(authed, "Portra", "35mm") == 0

    # the same goes for changing format
    other_format = await authed.patch(url, json={"format_id": gear["format120"]})
    assert other_format.status_code == 409
    assert "120" in other_format.json()["detail"]


async def test_flipping_flag_on_checks_stock(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = (
        await authed.post("/api/rolls", json=roll_body(gear, counts_against_stock=False))
    ).json()
    url = f"/api/rolls/{created['id']}"
    refused = await authed.patch(url, json={"counts_against_stock": True})
    assert refused.status_code == 409
    assert (await authed.get(url)).json()["counts_against_stock"] is False

    await purchase(authed, gear, 1)
    assert (await authed.patch(url, json={"counts_against_stock": True})).status_code == 200
    assert await stock_of(authed, "Tri-X", "35mm") == 0
    # turning it off again gives the roll back
    assert (await authed.patch(url, json={"counts_against_stock": False})).status_code == 200
    assert await stock_of(authed, "Tri-X", "35mm") == 1


async def test_other_edits_to_a_roll_do_not_recheck_stock(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    created = (await authed.post("/api/rolls", json=roll_body(gear))).json()  # stock now 0
    resp = await authed.patch(f"/api/rolls/{created['id']}", json={"subject": "Harbour", "ei": 800})
    assert resp.status_code == 200


async def test_deleting_a_roll_gives_the_film_back(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    created = (await authed.post("/api/rolls", json=roll_body(gear))).json()
    assert await stock_of(authed, "Tri-X", "35mm") == 0
    assert (await authed.delete(f"/api/rolls/{created['id']}")).status_code == 204
    assert await stock_of(authed, "Tri-X", "35mm") == 1


async def test_given_away_more_than_held_rejected(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 3)
    refused = await authed.post("/api/stock-movements", json=given_away(gear, 4))
    assert refused.status_code == 409
    assert await stock_of(authed, "Tri-X", "35mm") == 3
    assert (await authed.post("/api/stock-movements", json=given_away(gear, 3))).status_code == 201
    assert await stock_of(authed, "Tri-X", "35mm") == 0


async def test_deleting_purchase_that_rolls_depend_on_rejected(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bought = await purchase(authed, gear, 2)
    await authed.post("/api/rolls", json=roll_body(gear))
    refused = await authed.delete(f"/api/stock-movements/{bought['id']}")
    assert refused.status_code == 409
    assert await stock_of(authed, "Tri-X", "35mm") == 1
    # the movement is still there
    assert (await authed.get("/api/stock-movements")).json()["total"] == 1

    # with spare stock the delete is fine
    await purchase(authed, gear, 5)
    assert (await authed.delete(f"/api/stock-movements/{bought['id']}")).status_code == 204


async def test_editing_a_purchase_down_is_checked(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bought = await purchase(authed, gear, 5)
    for _ in range(3):
        await authed.post("/api/rolls", json=roll_body(gear))  # 2 left
    url = f"/api/stock-movements/{bought['id']}"
    assert (await authed.patch(url, json={"rolls": 2})).status_code == 409  # would be -1
    assert (await authed.patch(url, json={"rolls": 3})).status_code == 200  # exactly enough
    assert (await authed.patch(url, json={"rolls": 8})).status_code == 200  # up is always fine
    assert (await authed.patch(url, json={"notes": "x"})).status_code == 200


async def test_moving_a_purchase_to_another_film_is_checked(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bought = await purchase(authed, gear, 2)
    await authed.post("/api/rolls", json=roll_body(gear))
    url = f"/api/stock-movements/{bought['id']}"
    assert (await authed.patch(url, json={"film_id": gear["film2"]})).status_code == 409
    assert await stock_of(authed, "Tri-X", "35mm") == 1


async def test_editing_a_given_away_to_take_more_is_checked(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 4)
    gift = (await authed.post("/api/stock-movements", json=given_away(gear, 1))).json()
    url = f"/api/stock-movements/{gift['id']}"
    assert (await authed.patch(url, json={"rolls": -5})).status_code == 409
    assert (await authed.patch(url, json={"rolls": -4})).status_code == 200
    assert (await authed.patch(url, json={"rolls": -1})).status_code == 200  # fewer is fine


async def test_deleting_a_given_away_returns_stock_and_is_never_blocked(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    gift = (await authed.post("/api/stock-movements", json=given_away(gear, 1))).json()
    assert (await authed.delete(f"/api/stock-movements/{gift['id']}")).status_code == 204
    assert await stock_of(authed, "Tri-X", "35mm") == 1


async def test_bulk_load_edit_down_is_checked(
    authed: AsyncClient, gear: dict[str, str], engine: Any
) -> None:
    from tests.stock.test_stock_api import make_bulk

    bulk = await make_bulk(engine, gear["film"])
    load = (
        await authed.post(
            "/api/stock-movements",
            json={
                "kind": "bulk_load",
                "bulk_roll_id": str(bulk),
                "occurred_on": "2026-11-06",
                "rolls": 3,
                "exposures_per_cassette": 36,
            },
        )
    ).json()
    for _ in range(2):
        assert (await authed.post("/api/rolls", json=roll_body(gear))).status_code == 201
    url = f"/api/stock-movements/{load['id']}"
    assert (await authed.patch(url, json={"rolls": 1})).status_code == 409
    assert (await authed.patch(url, json={"rolls": 2})).status_code == 200
    assert (await authed.delete(url)).status_code == 409


async def test_adjustment_can_always_repair_and_deleting_one_is_checked(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    adj = (
        await authed.post(
            "/api/stock-adjustments",
            json={
                "film_id": gear["film"],
                "format_id": gear["format35"],
                "counted": 2,
                "occurred_on": "2026-11-05",
            },
        )
    ).json()
    for _ in range(2):
        await authed.post("/api/rolls", json=roll_body(gear))
    assert (await authed.delete(f"/api/stock-movements/{adj['id']}")).status_code == 409


# --- concurrency -----------------------------------------------------------------------


async def test_two_concurrent_rolls_for_last_cassette_one_wins(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    results = await asyncio.gather(
        authed.post("/api/rolls", json=roll_body(gear, subject="a")),
        authed.post("/api/rolls", json=roll_body(gear, subject="b")),
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert await stock_of(authed, "Tri-X", "35mm") == 0
    assert (await authed.get("/api/rolls")).json()["total"] == 1


async def test_many_concurrent_writes_never_overdraw(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 3)
    calls = [authed.post("/api/rolls", json=roll_body(gear)) for _ in range(5)]
    calls += [authed.post("/api/stock-movements", json=given_away(gear, 1)) for _ in range(3)]
    results = await asyncio.gather(*calls)
    ok = [r for r in results if r.status_code == 201]
    refused = [r for r in results if r.status_code == 409]
    assert len(ok) == 3  # exactly the three rolls that were there
    assert len(ok) + len(refused) == 8
    assert await stock_of(authed, "Tri-X", "35mm") == 0


async def test_concurrent_roll_and_delete_of_purchase_never_overdraw(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    bought = await purchase(authed, gear, 1)
    results = await asyncio.gather(
        authed.post("/api/rolls", json=roll_body(gear)),
        authed.delete(f"/api/stock-movements/{bought['id']}"),
    )
    codes = sorted(r.status_code for r in results)
    assert codes in ([201, 409], [204, 409])  # one or the other, never both
    assert await stock_of(authed, "Tri-X", "35mm") >= 0


async def test_writers_on_different_pairs_do_not_block_each_other(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    await purchase(authed, gear, 1, film="film2", fmt="format120")
    results = await asyncio.gather(
        authed.post("/api/rolls", json=roll_body(gear)),
        authed.post(
            "/api/rolls", json=roll_body(gear, film_id=gear["film2"], format_id=gear["format120"])
        ),
    )
    assert [r.status_code for r in results] == [201, 201]


async def test_moves_between_pairs_in_opposite_directions_do_not_deadlock(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await purchase(authed, gear, 1)
    await purchase(authed, gear, 1, film="film2")
    a = (await authed.post("/api/rolls", json=roll_body(gear))).json()
    b = (await authed.post("/api/rolls", json=roll_body(gear, film_id=gear["film2"]))).json()
    # swap their films at the same time: each lock set is {Tri-X, Portra}, taken in sorted order
    results = await asyncio.wait_for(
        asyncio.gather(
            authed.patch(f"/api/rolls/{a['id']}", json={"film_id": gear["film2"]}),
            authed.patch(f"/api/rolls/{b['id']}", json={"film_id": gear["film"]}),
        ),
        timeout=20,
    )
    assert all(r.status_code in (200, 409) for r in results)
    assert await stock_of(authed, "Tri-X", "35mm") >= 0
    assert await stock_of(authed, "Portra", "35mm") >= 0
    assert uuid.UUID(a["id"]) != uuid.UUID(b["id"])
