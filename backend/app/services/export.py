"""CSV export of the domain tables.

Only tables on `EXPORT_TABLES` can be exported: new tables are private until added here, and the
tables holding secrets (sessions, tokens, OAuth) and bookkeeping (users, import ledger,
alembic_version) are not on it.
"""

import csv
import io
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base

EXPORT_TABLES: tuple[str, ...] = (
    "bulk_rolls",
    "cameras",
    "dev_time_refs",
    "developers",
    "filters",
    "films",
    "formats",
    "lenses",
    "rolls",
    "settings",
    "stock_movements",
)

# A spreadsheet treats text starting with one of these as a formula. Text cells that do get a
# leading apostrophe, which spreadsheets hide and which keeps notes like "=1+1" inert. Numbers
# are never touched (a negative stock count stays -2).
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class UnknownTableError(LookupError):
    pass


def _table(name: str) -> Table:
    if name not in EXPORT_TABLES:
        raise UnknownTableError(name)
    return Base.metadata.tables[name]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date | UUID | Decimal | int):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def _line(values: list[str]) -> str:
    out = io.StringIO()
    csv.writer(out).writerow(values)
    return out.getvalue()


async def export_table(session: AsyncSession, table: str) -> AsyncIterator[str]:
    """CSV text, header row first, then one row per record in a stable order (the primary key,
    or all columns for a table without one). Raises UnknownTableError for any other name."""
    source = _table(table)
    yield _line([column.name for column in source.columns])
    keys = list(source.primary_key.columns) or list(source.columns)
    result = await session.stream(select(source).order_by(*keys).execution_options(yield_per=500))
    async for row in result:
        yield _line([_cell(value) for value in row])
