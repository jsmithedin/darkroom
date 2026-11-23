from datetime import UTC, date, datetime, tzinfo
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState

from app.services.stats import camera_idle, get_stats, london_today
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
    for path in ("/api/stats", "/api/stats/camera-idle", "/api/stats/spend"):
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
