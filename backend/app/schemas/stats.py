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
