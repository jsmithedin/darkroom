from datetime import date
from uuid import UUID

from pydantic import BaseModel


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
    name: str
    last_used: date | None


class SpendYear(BaseModel):
    year: int
    purchases_pence: int
    bulk_pence: int
    rolls: int
    cost_per_roll_pence: int | None


class LowStockFilm(BaseModel):
    id: UUID
    name: str
    type: str


class LowStockFormat(BaseModel):
    id: UUID
    name: str


class LowStock(BaseModel):
    """Film regularly developed and close to running out, with the figures behind the call."""

    film: LowStockFilm
    format: LowStockFormat
    rolls_remaining: int
    rolls_developed: int
    window_days: int
    days_of_stock: int
