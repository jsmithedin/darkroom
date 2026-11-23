from datetime import UTC, date, datetime, tzinfo
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState

from app.services.stats import camera_idle, get_stats, london_today, low_stock
from tests.support import roll_body


def test_london_today_between_midnight_and_1am_bst() -> None:
    now = datetime(2026, 7, 1, 23, 30, tzinfo=UTC)
    assert london_today(now, "Europe/London") == date(2026, 7, 2)
    assert london_today(now, "UTC") == date(2026, 7, 1)


async def add_roll(client: AsyncClient, gear: dict[str, str], day: str, **fields: str) -> None:
    result = await client.post(
        "/api/rolls", json=roll_body(gear, dev_date=day, counts_against_stock=False, **fields)
    )
    assert result.status_code == 201, result.text


async def test_cumulative_stops_at_current_month(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    for day in ("2025-12-01", "2026-01-01", "2026-06-01", "2026-08-01"):
        await add_roll(authed, gear, day)
    stats = await get_stats(db_session, 2026, date(2026, 7, 2))
    assert len(stats.monthly) == len(stats.previous_monthly) == 12
    assert [point.cumulative for point in stats.monthly] == [1] * 5 + [2, 2] + [None] * 5
    assert stats.monthly[7].count == 1
    assert stats.previous_monthly[-1].count == stats.previous_monthly[-1].cumulative == 1


async def test_ytd_compares_to_same_date_last_year(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    for day in ("2023-02-28", "2023-03-01", "2024-02-29", "2024-03-01"):
        await add_roll(authed, gear, day)
    stats = await get_stats(db_session, 2024, date(2024, 2, 29))
    assert stats.ytd.model_dump() == {"this_year": 1, "last_year_to_date": 1}
    historical = await get_stats(db_session, 2024, date(2026, 2, 28))
    assert historical.ytd.model_dump() == {"this_year": 2, "last_year_to_date": 2}


async def test_future_year_has_no_cumulative_points(db_session: AsyncSession) -> None:
    stats = await get_stats(db_session, 2027, date(2026, 7, 2))
    assert [point.cumulative for point in stats.monthly] == [None] * 12
    assert stats.ytd.model_dump() == {"this_year": 0, "last_year_to_date": 0}


async def test_stats_aggregates_use_one_statement(db_session: AsyncSession) -> None:
    statements = 0

    def count_statement(_: ORMExecuteState) -> None:
        nonlocal statements
        statements += 1

    event.listen(db_session.sync_session, "do_orm_execute", count_statement)
    try:
        await get_stats(db_session, 2026, date(2026, 7, 2))
    finally:
        event.remove(db_session.sync_session, "do_orm_execute", count_statement)
    assert statements == 1


async def test_breakdowns_sum_to_total(authed: AsyncClient, gear: dict[str, str]) -> None:
    await add_roll(authed, gear, "2025-01-01")
    await add_roll(authed, gear, "2025-02-01", film_id=gear["film2"], source="bulk")
    film = await authed.post("/api/films", json={"name": "HP5", "type": "bw", "box_iso": 400})
    assert film.status_code == 201, film.text
    await add_roll(authed, gear, "2025-03-01", film_id=film.json()["id"])
    await add_roll(authed, gear, "2026-01-01")
    result = await authed.get("/api/stats", params={"year": 2025})
    assert result.status_code == 200, result.text
    groups = result.json()["breakdowns"]
    assert set(groups) == {"camera", "film", "developer", "format", "type", "source"}
    assert all(sum(row["count"] for row in rows) == 3 for rows in groups.values())
    assert groups["camera"] == [{"id": gear["camera"], "name": "Nikon FM2", "count": 3}]
    assert groups["type"][0] == {"id": None, "name": "bw", "count": 2}
    assert {row["name"] for row in groups["source"]} == {"factory", "bulk"}


async def test_camera_idle_oldest_first(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    await add_roll(authed, gear, "2024-03-01")
    await add_roll(authed, gear, "2025-04-01")
    await add_roll(authed, gear, "2024-09-01", camera_id=gear["camera2"])
    unused = await authed.post("/api/cameras", json={"name": "Unused"})
    archived = await authed.post("/api/cameras", json={"name": "Archived"})
    assert unused.status_code == archived.status_code == 201
    archived_id = archived.json()["id"]
    await add_roll(authed, gear, "2023-01-01", camera_id=archived_id)
    response = await authed.post(f"/api/cameras/{archived_id}/archive")
    assert response.status_code == 200, response.text
    result = await camera_idle(db_session)
    assert [(row.camera_id, row.name, row.last_used) for row in result] == [
        (UUID(unused.json()["id"]), "Unused", None),
        (UUID(gear["camera2"]), "Olympus XA", date(2024, 9, 1)),
        (UUID(gear["camera"]), "Nikon FM2", date(2025, 4, 1)),
    ]


async def test_spend_excludes_unpriced_and_undated_bulk(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    purchase = await authed.post(
        "/api/stock-movements",
        json={
            "kind": "purchase",
            "film_id": gear["film"],
            "format_id": gear["format35"],
            "occurred_on": "2025-02-01",
            "cost_pence": 501,
            "rolls": 2,
        },
    )
    assert purchase.status_code == 201, purchase.text
    for label, price, day in (
        ("priced", 300, "2025-03-01"),
        ("spend only", 100, "2026-03-01"),
        ("unpriced", None, "2023-03-01"),
        ("undated", 900, None),
    ):
        spool = await authed.post(
            "/api/bulk-rolls",
            json={
                "label": label,
                "film_id": gear["film"],
                "length_mm": 10000,
                "cost_pence": price,
                "bought_on": day,
            },
        )
        assert spool.status_code == 201, spool.text
    for day in ("2024-01-01", "2025-01-01", "2025-12-01"):
        await add_roll(authed, gear, day)
    result = await authed.get("/api/stats/spend")
    assert result.status_code == 200, result.text
    assert result.json() == [
        {"year": 2024, "purchases_pence": 0, "bulk_pence": 0, "rolls": 1, "cost_per_roll_pence": 0},
        {
            "year": 2025,
            "purchases_pence": 501,
            "bulk_pence": 300,
            "rolls": 2,
            "cost_per_roll_pence": 401,
        },
        {
            "year": 2026,
            "purchases_pence": 0,
            "bulk_pence": 100,
            "rolls": 0,
            "cost_per_roll_pence": None,
        },
    ]


async def test_stats_require_sign_in(client: AsyncClient) -> None:
    for path in (
        "/api/stats",
        "/api/stats/camera-idle",
        "/api/stats/spend",
        "/api/stats/low-stock",
    ):
        assert (await client.get(path)).status_code == 401


@pytest.mark.parametrize(("year", "status"), [(1899, 422), (1900, 200), (2200, 200), (2201, 422)])
async def test_stats_year_range(authed: AsyncClient, year: int, status: int) -> None:
    assert (await authed.get("/api/stats", params={"year": year})).status_code == status


async def test_default_year_uses_configured_timezone(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import stats

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return datetime(2025, 12, 31, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(stats, "datetime", FixedClock)
    response = await authed.patch("/api/settings", json={"timezone": "Europe/Paris"})
    assert response.status_code == 200, response.text
    result = await authed.get("/api/stats")
    assert result.status_code == 200, result.text
    assert result.json()["year"] == 2026


async def stock_up(
    client: AsyncClient, gear: dict[str, str], rolls: int, fmt: str = "format35"
) -> None:
    result = await client.post(
        "/api/stock-movements",
        json={
            "kind": "purchase",
            "film_id": gear["film"],
            "format_id": gear[fmt],
            "occurred_on": "2026-01-01",
            "rolls": rolls,
            "cost_pence": 0,
        },
    )
    assert result.status_code == 201, result.text


async def test_low_stock_rule(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    today = date(2026, 11, 23)
    for day in ("2026-09-01", "2026-10-01", "2026-11-01", "2026-11-10", "2026-11-20", "2026-11-22"):
        await add_roll(authed, gear, day)  # six rolls in the window
    await stock_up(authed, gear, 2)
    [row] = await low_stock(db_session, today)
    assert (row.rolls_remaining, row.rolls_developed, row.days_of_stock) == (2, 6, 30)

    await stock_up(authed, gear, 1)  # three left: 45 days of cover
    assert await low_stock(db_session, today) == []


async def test_low_stock_needs_regular_use_and_ignores_purchases(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    today = date(2026, 11, 23)
    for day in ("2026-11-01", "2026-11-10"):  # two rolls: not regular
        await add_roll(authed, gear, day)
    assert await low_stock(db_session, today) == []
    await add_roll(authed, gear, "2026-08-25")  # 90 days back from today is 2026-08-26: outside
    assert await low_stock(db_session, today) == []
    await add_roll(authed, gear, "2026-08-26")  # inside the window: third roll
    [row] = await low_stock(db_session, today)
    assert (row.rolls_remaining, row.rolls_developed) == (0, 3)


async def test_low_stock_covers_zero_and_negative_balances_per_format(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    today = date(2026, 11, 23)
    for day in ("2026-11-01", "2026-11-02", "2026-11-03"):
        await add_roll(authed, gear, day)  # 35mm
        await add_roll(authed, gear, day, format_id=gear["format120"])
    await stock_up(authed, gear, 50, "format120")  # plenty of 120
    rows = await low_stock(db_session, today)
    assert [(r.format.name, r.rolls_remaining) for r in rows] == [("35mm", 0)]


async def test_low_stock_endpoint(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.get("/api/stats/low-stock")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_low_stock_negative_balance_archived_and_edges(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    today = date(2026, 11, 23)
    await stock_up(authed, gear, 1)
    for day in ("2026-11-23", "2026-11-22", "2026-11-21"):
        await add_roll(authed, gear, day)
    await add_roll(authed, gear, "2026-11-24")  # tomorrow: not usage
    [row] = await low_stock(db_session, today)
    assert (row.rolls_developed, row.rolls_remaining) == (3, 1)

    # a counted roll after the purchase is removed leaves a negative balance
    resp = await authed.post(
        "/api/rolls", json=roll_body(gear, dev_date="2026-11-20", counts_against_stock=True)
    )
    assert resp.status_code == 201, resp.text
    await db_session.execute(text("DELETE FROM stock_movements"))
    [row] = await low_stock(db_session, today)
    assert (row.rolls_remaining, row.days_of_stock) == (-1, 0)

    # archive the film: it is no longer flagged
    assert (await authed.post(f"/api/films/{gear['film']}/archive")).status_code in (200, 204)
    assert await low_stock(db_session, today) == []


async def test_low_stock_flags_bulk_spool_and_sorts(
    authed: AsyncClient, gear: dict[str, str], db_session: AsyncSession
) -> None:
    today = date(2026, 11, 23)
    for day in ("2026-11-01", "2026-11-02", "2026-11-03"):
        await add_roll(authed, gear, day)
    await authed.post(
        "/api/bulk-rolls", json={"label": "Spool", "film_id": gear["film"], "length_mm": 17_000}
    )
    [row] = await low_stock(db_session, today)
    assert row.on_bulk_spool is True
    assert row.film.type in ("bw", "colour", "slide")


async def test_low_stock_endpoint_shape(authed: AsyncClient, gear: dict[str, str]) -> None:
    from datetime import timedelta

    day = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    for _ in range(3):
        await add_roll(authed, gear, day)
    [row] = (await authed.get("/api/stats/low-stock")).json()
    assert row["window_days"] == 90
    assert row["rolls_developed"] == 3
    assert row["days_of_stock"] == 0
    assert isinstance(row["film"]["type"], str)
