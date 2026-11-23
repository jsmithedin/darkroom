from calendar import monthrange
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import extract, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import BulkRoll, Camera, Developer, Film, Format, Roll, StockMovement


class MonthPoint(BaseModel):
    month: int
    count: int
    cumulative: int | None


class YtdCompare(BaseModel):
    this_year: int
    last_year_to_date: int


class BreakdownRow(BaseModel):
    id: UUID | None = None
    name: str
    count: int


class Stats(BaseModel):
    year: int
    monthly: list[MonthPoint]
    previous_monthly: list[MonthPoint]
    ytd: YtdCompare
    breakdowns: dict[str, list[BreakdownRow]]


class CameraIdle(BaseModel):
    camera_id: UUID
    last_used: date


class SpendYear(BaseModel):
    year: int
    purchases_pence: int
    bulk_pence: int
    rolls: int
    cost_per_roll_pence: int | None


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


async def _breakdown(
    db: AsyncSession,
    start: date,
    end: date,
    name: InstrumentedAttribute[str],
    ref_id: InstrumentedAttribute[UUID] | None = None,
) -> list[BreakdownRow]:
    count = func.count()
    identity = [ref_id] if ref_id is not None else []
    query = select(name, count, ref_id if ref_id is not None else literal(None)).select_from(Roll)
    if name.class_ is not Roll:
        query = query.join(name.class_)
    rows = await db.execute(
        query.where(Roll.dev_date.between(start, end))
        .group_by(name, *identity)
        .order_by(count.desc(), name, *identity)
    )
    return [BreakdownRow(name=label, count=n, id=item_id) for label, n, item_id in rows]


async def get_stats(db: AsyncSession, year: int, today: date) -> Stats:
    """Summarise a calendar year and compare elapsed days with the preceding year."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    previous_start = date(year - 1, 1, 1)
    month = extract("month", Roll.dev_date)
    roll_year = extract("year", Roll.dev_date)
    counts: dict[int, dict[int, int]] = {year - 1: {}, year: {}}
    rows = await db.execute(
        select(roll_year, month, func.count())
        .where(Roll.dev_date.between(previous_start, end))
        .group_by(roll_year, month)
    )
    for y, m, count in rows:
        counts[int(y)][int(m)] = count

    ytd = YtdCompare(this_year=0, last_year_to_date=0)
    if year <= today.year:
        current_end = today if year == today.year else end
        m, day = current_end.month, current_end.day
        previous_end = date(year - 1, m, min(day, monthrange(year - 1, m)[1]))
        this_year, previous = (
            await db.execute(
                select(
                    func.count().filter(Roll.dev_date.between(start, current_end)),
                    func.count().filter(Roll.dev_date.between(previous_start, previous_end)),
                ).where(Roll.dev_date.between(previous_start, current_end))
            )
        ).one()
        ytd = YtdCompare(this_year=this_year, last_year_to_date=previous)

    return Stats(
        year=year,
        monthly=_month_points(counts[year], year, today),
        previous_monthly=_month_points(counts[year - 1], year - 1, today),
        ytd=ytd,
        breakdowns={
            "camera": await _breakdown(db, start, end, Camera.name, Camera.id),
            "film": await _breakdown(db, start, end, Film.name, Film.id),
            "developer": await _breakdown(db, start, end, Developer.name, Developer.id),
            "format": await _breakdown(db, start, end, Format.name, Format.id),
            "type": await _breakdown(db, start, end, Film.type),
            "source": await _breakdown(db, start, end, Roll.source),
        },
    )


async def camera_idle(db: AsyncSession) -> list[CameraIdle]:
    last_used = func.max(Roll.dev_date)
    rows = await db.execute(
        select(Roll.camera_id, last_used)
        .group_by(Roll.camera_id)
        .order_by(last_used, Roll.camera_id)
    )
    return [CameraIdle(camera_id=camera_id, last_used=day) for camera_id, day in rows]


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
