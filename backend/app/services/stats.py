from calendar import monthrange
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, ScalarSelect, extract, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import BulkRoll, Camera, Developer, Film, Format, Roll, StockMovement
from app.schemas.stats import BreakdownRow, CameraIdle, MonthPoint, SpendYear, Stats, YtdCompare


def london_today(now_utc: datetime, tz: str) -> date:
    return now_utc.astimezone(ZoneInfo(tz)).date()


def _month_points(counts: dict[int, int], year: int, today: date) -> list[MonthPoint]:
    last_month = 12
    if year >= today.year:
        last_month = today.month if year == today.year else 0
    cumulative = 0
    points = []
    for month in range(1, 13):
        count = counts.get(month, 0)
        cumulative += count
        points.append(
            MonthPoint(
                month=month, count=count, cumulative=cumulative if month <= last_month else None
            )
        )
    return points


def _breakdown(
    start: date,
    end: date,
    name: InstrumentedAttribute[str],
    ref_id: InstrumentedAttribute[UUID] | None = None,
) -> ScalarSelect[Any]:
    identity = [ref_id] if ref_id is not None else []
    item_id = ref_id if ref_id is not None else literal(None)
    query = select(name.label("name"), func.count().label("count"), item_id.label("id"))
    query = query.select_from(Roll)
    if name.class_ is not Roll:
        query = query.join(name.class_)
    rows = query.where(Roll.dev_date.between(start, end)).group_by(name, *identity).subquery()
    ordered_rows = aggregate_order_by(
        rows.table_valued(), rows.c.count.desc(), rows.c.name, rows.c.id
    )
    return select(func.jsonb_agg(ordered_rows, type_=JSONB)).scalar_subquery()


def _roll_count(start: date, end: date) -> ScalarSelect[int]:
    return select(func.count()).where(Roll.dev_date.between(start, end)).scalar_subquery()


async def get_stats(db: AsyncSession, year: int, today: date) -> Stats:
    """Summarise a calendar year and compare elapsed days with the preceding year."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    previous_start = date(year - 1, 1, 1)
    month = extract("month", Roll.dev_date)
    roll_year = extract("year", Roll.dev_date)
    monthly = (
        select(roll_year.label("year"), month.label("month"), func.count().label("count"))
        .where(Roll.dev_date.between(previous_start, end))
        .group_by(roll_year, month)
        .subquery()
    )
    this_ytd: ColumnElement[int] = literal(0)
    previous_ytd: ColumnElement[int] = literal(0)
    if year <= today.year:
        current_end = today if year == today.year else end
        m, day = current_end.month, current_end.day
        previous_end = date(year - 1, m, min(day, monthrange(year - 1, m)[1]))
        this_ytd = _roll_count(start, current_end)
        previous_ytd = _roll_count(previous_start, previous_end)

    breakdowns = {
        "camera": _breakdown(start, end, Camera.name, Camera.id),
        "film": _breakdown(start, end, Film.name, Film.id),
        "developer": _breakdown(start, end, Developer.name, Developer.id),
        "format": _breakdown(start, end, Format.name, Format.id),
        "type": _breakdown(start, end, Film.type),
        "source": _breakdown(start, end, Roll.source),
    }
    # A single statement gives every aggregate the same PostgreSQL snapshot.
    result = (
        await db.execute(
            select(
                select(func.jsonb_agg(monthly.table_valued(), type_=JSONB)).scalar_subquery(),
                this_ytd,
                previous_ytd,
                *breakdowns.values(),
            )
        )
    ).one()
    monthly_rows, this_year, last_year_to_date, *breakdown_rows = result
    counts: dict[int, dict[int, int]] = {year - 1: {}, year: {}}
    for row in monthly_rows or []:
        counts[row["year"]][row["month"]] = row["count"]
    return Stats(
        year=year,
        monthly=_month_points(counts[year], year, today),
        previous_monthly=_month_points(counts[year - 1], year - 1, today),
        ytd=YtdCompare(this_year=this_year, last_year_to_date=last_year_to_date),
        breakdowns={
            kind: [BreakdownRow.model_validate(row) for row in rows or []]
            for kind, rows in zip(breakdowns, breakdown_rows, strict=True)
        },
    )


async def camera_idle(db: AsyncSession) -> list[CameraIdle]:
    last_used = func.max(Roll.dev_date)
    rows = await db.execute(
        select(Camera.id, Camera.name, last_used)
        .outerjoin(Roll, Roll.camera_id == Camera.id)
        .where(Camera.archived_at.is_(None))
        .group_by(Camera.id)
        .order_by(last_used.asc().nulls_first(), Camera.name, Camera.id)
    )
    return [
        CameraIdle(camera_id=camera_id, name=name, last_used=day) for camera_id, name, day in rows
    ]


async def spend(db: AsyncSession) -> list[SpendYear]:
    purchase_year = extract("year", StockMovement.occurred_on)
    bulk_year = extract("year", BulkRoll.bought_on)
    roll_year = extract("year", Roll.dev_date)
    activity = union_all(
        select(
            purchase_year.label("year"),
            func.sum(StockMovement.cost_pence).label("purchases"),
            literal(0).label("bulk"),
            literal(0).label("rolls"),
        )
        .where(StockMovement.kind == "purchase")
        .group_by(purchase_year),
        select(bulk_year, literal(0), func.sum(BulkRoll.cost_pence), literal(0))
        .where(BulkRoll.bought_on.is_not(None), BulkRoll.cost_pence.is_not(None))
        .group_by(bulk_year),
        select(roll_year, literal(0), literal(0), func.count()).group_by(roll_year),
    ).subquery()
    rows = await db.execute(
        select(
            activity.c.year,
            func.sum(activity.c.purchases),
            func.sum(activity.c.bulk),
            func.sum(activity.c.rolls),
        )
        .group_by(activity.c.year)
        .order_by(activity.c.year)
    )
    results = []
    for year, purchases, bulk, rolls in rows:
        purchases, bulk, rolls = int(purchases), int(bulk), int(rolls)
        total = purchases + bulk
        results.append(
            SpendYear(
                year=int(year),
                purchases_pence=purchases,
                bulk_pence=bulk,
                rolls=rolls,
                cost_per_roll_pence=(2 * total + rolls) // (2 * rolls) if rolls else None,
            )
        )
    return results
