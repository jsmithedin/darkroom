"""Compare the database with the totals the sheet is known to have."""

from dataclasses import dataclass, field

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BulkRoll, Format, Roll, StockMovement
from app.models.stock import stock_levels


@dataclass(frozen=True)
class Expected:
    """The sheet's own totals at the opening date (design spec, section 10)."""

    total_rolls: int = 117
    rolls_per_year: dict[int, int] = field(default_factory=lambda: {2025: 60, 2026: 57})
    stock_by_format: dict[str, int] = field(default_factory=lambda: {"35mm": 61, "120": 88})
    bulk_left_mm: dict[str, int] = field(default_factory=lambda: {"Bulk 1": 7300})


@dataclass(frozen=True)
class Reconciliation:
    total_rolls: int
    rolls_per_year: dict[int, int]
    stock_by_format: dict[str, int]
    bulk_left_mm: dict[str, int]

    def check(self, expected: Expected) -> list[str]:
        """One line per figure that differs; empty means everything matches."""
        problems: list[str] = []
        if self.total_rolls != expected.total_rolls:
            problems.append(f"total rolls: expected {expected.total_rolls}, got {self.total_rolls}")
        years = set(expected.rolls_per_year) | set(self.rolls_per_year)
        for year in sorted(years):
            want, got = expected.rolls_per_year.get(year, 0), self.rolls_per_year.get(year, 0)
            if want != got:
                problems.append(f"rolls in {year}: expected {want}, got {got}")
        formats = set(expected.stock_by_format) | set(self.stock_by_format)
        for fmt in sorted(formats):
            want, got = expected.stock_by_format.get(fmt, 0), self.stock_by_format.get(fmt, 0)
            if want != got:
                problems.append(f"stock of {fmt}: expected {want}, got {got}")
        for label in sorted(set(expected.bulk_left_mm) | set(self.bulk_left_mm)):
            wanted = expected.bulk_left_mm.get(label)
            actual = self.bulk_left_mm.get(label)
            if wanted != actual:
                problems.append(f"{label} left (mm): expected {wanted}, got {actual}")
        return problems

    def report(self) -> str:
        years = ", ".join(f"{y}: {n}" for y, n in sorted(self.rolls_per_year.items()))
        stock = ", ".join(f"{n} x {f}" for f, n in sorted(self.stock_by_format.items()))
        bulk = ", ".join(f"{b}: {mm / 1000:g} m" for b, mm in sorted(self.bulk_left_mm.items()))
        return (
            f"Total rolls: {self.total_rolls}\n"
            f"Rolls per year: {years}\n"
            f"Stock: {stock}\n"
            f"Bulk left: {bulk}"
        )


async def reconcile(session: AsyncSession) -> Reconciliation:
    """Read the figures back from the database (not from what the importer thinks it wrote)."""
    total = (await session.execute(select(func.count()).select_from(Roll))).scalar_one()
    year = extract("year", Roll.dev_date)
    per_year = {
        int(y): int(n)
        for y, n in (await session.execute(select(year, func.count()).group_by(year))).all()
    }
    stock = {
        str(name): int(n)
        for name, n in (
            await session.execute(
                select(Format.name, func.sum(stock_levels.c.rolls))
                .join(Format, Format.id == stock_levels.c.format_id)
                .group_by(Format.name)
            )
        ).all()
        if n
    }
    loaded = (
        select(
            StockMovement.bulk_roll_id.label("bulk_id"),
            func.coalesce(func.sum(StockMovement.metres_mm), 0).label("mm"),
        )
        .where(StockMovement.kind == "bulk_load")
        .group_by(StockMovement.bulk_roll_id)
        .subquery()
    )
    bulk = {
        str(label): int(length - used - mm)
        for label, length, used, mm in (
            await session.execute(
                select(
                    BulkRoll.label,
                    BulkRoll.length_mm,
                    BulkRoll.used_before_mm,
                    func.coalesce(loaded.c.mm, 0),
                ).outerjoin(loaded, loaded.c.bulk_id == BulkRoll.id)
            )
        ).all()
    }
    return Reconciliation(int(total), per_year, stock, bulk)
