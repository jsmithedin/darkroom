import uuid
from typing import Any

from httpx import AsyncClient

from tests.stock.test_stock_api import post, purchase, stock


def body(g: dict[str, str], counts: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    return {
        "batch_id": str(uuid.uuid4()),
        "occurred_on": "2026-11-23",
        "counts": [{"film_id": g["film"], "format_id": g["format35"], **c} for c in counts],
    } | over


async def test_records_only_differences_and_counts_unstocked_film(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=5))
    ok = await authed.post(
        "/api/stocktakes",
        json=body(gear, [{"counted": 3, "expected": 5}])
        | {
            "counts": [
                {
                    "film_id": gear["film"],
                    "format_id": gear["format35"],
                    "counted": 3,
                    "expected": 5,
                },
                {
                    "film_id": gear["film"],
                    "format_id": gear["format120"],
                    "counted": 0,
                    "expected": 0,
                },
            ]
        },
    )
    assert ok.status_code == 201, ok.text
    out = ok.json()
    assert out["replayed"] is False
    assert [(a["rolls"], a["counted_to"]) for a in out["adjustments"]] == [(-2, 3)]
    assert sum((await stock(authed, include_zero=True)).values()) == 3


async def test_counting_film_with_no_history_adds_stock(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    resp = await authed.post("/api/stocktakes", json=body(gear, [{"counted": 4, "expected": 0}]))
    assert resp.status_code == 201, resp.text
    assert sum((await stock(authed)).values()) == 4


async def test_retry_with_same_batch_does_not_duplicate(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=5))
    payload = body(gear, [{"counted": 2, "expected": 5}])
    first = await authed.post("/api/stocktakes", json=payload)
    again = await authed.post("/api/stocktakes", json=payload)
    assert again.status_code == 201, again.text
    assert again.json()["replayed"] is True
    assert again.json()["adjustments"] == first.json()["adjustments"]
    moves = (await authed.get("/api/stock-movements", params={"kind": "adjustment"})).json()
    assert moves["total"] == 1
    assert sum((await stock(authed)).values()) == 2


async def test_changed_stock_flags_rows_and_applies_nothing(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=5))
    payload = body(gear, [{"counted": 2, "expected": 5}])
    payload["counts"].append(
        {"film_id": gear["film"], "format_id": gear["format120"], "counted": 1, "expected": 0}
    )
    await post(authed, purchase(gear, rolls=1))  # stock moves after review
    resp = await authed.post("/api/stocktakes", json=payload)
    assert resp.status_code == 409
    detail = resp.json()
    assert detail["detail"]
    assert detail["code"] == "stock_changed"
    assert [(r["format_id"], r["expected"], r["current"]) for r in detail["rows"]] == [
        (gear["format35"], 5, 6)
    ]
    assert sum((await stock(authed)).values()) == 6


async def test_validation(authed: AsyncClient, gear: dict[str, str]) -> None:
    dup = body(gear, [{"counted": 1, "expected": 0}, {"counted": 2, "expected": 0}])
    assert (await authed.post("/api/stocktakes", json=dup)).status_code == 422
    neg = body(gear, [{"counted": -1, "expected": 0}])
    assert (await authed.post("/api/stocktakes", json=neg)).status_code == 422
    empty = body(gear, [])
    assert (await authed.post("/api/stocktakes", json=empty)).status_code == 422
    unknown = body(gear, [{"counted": 1, "expected": 0, "film_id": str(uuid.uuid4())}])
    assert (await authed.post("/api/stocktakes", json=unknown)).status_code == 422


async def test_replay_lists_adjustments_in_the_same_order(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await post(authed, purchase(gear, rolls=5))
    payload = body(gear, [{"counted": 2, "expected": 5}])
    payload["counts"].append(
        {"film_id": gear["film"], "format_id": gear["format120"], "counted": 3, "expected": 0}
    )
    first = (await authed.post("/api/stocktakes", json=payload)).json()
    again = (await authed.post("/api/stocktakes", json=payload)).json()
    assert len(first["adjustments"]) == 2
    assert [a["id"] for a in again["adjustments"]] == [a["id"] for a in first["adjustments"]]


async def test_all_matching_counts_write_nothing(authed: AsyncClient, gear: dict[str, str]) -> None:
    await post(authed, purchase(gear, rolls=5))
    resp = await authed.post("/api/stocktakes", json=body(gear, [{"counted": 5, "expected": 5}]))
    assert resp.status_code == 201
    assert resp.json()["adjustments"] == []
    moves = (await authed.get("/api/stock-movements", params={"kind": "adjustment"})).json()
    assert moves["total"] == 0


async def test_count_over_the_limit_is_rejected(authed: AsyncClient, gear: dict[str, str]) -> None:
    over = body(gear, [{"counted": 100_001, "expected": 0}])
    assert (await authed.post("/api/stocktakes", json=over)).status_code == 422
