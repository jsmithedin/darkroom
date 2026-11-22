import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import Roll
from app.models.reference import MODELS, RefKind
from app.schemas.rolls import RollIn, RollUpdate
from app.services.stock import Pair, assert_non_negative, lock_pairs


class NotFoundError(Exception):
    """No such roll (or camera)."""


class InvalidReferenceError(Exception):
    """A camera, lens, film... id is unknown, or archived and newly chosen."""


@dataclass(frozen=True)
class RollFilters:
    date_from: date | None = None
    date_to: date | None = None
    film_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    developer_id: uuid.UUID | None = None
    source: str | None = None
    q: str | None = None


@dataclass(frozen=True)
class Page:
    limit: int = 50
    offset: int = 0


# roll column -> (reference kind, singular name for messages)
REFS: dict[str, tuple[RefKind, str]] = {
    "camera_id": (RefKind.CAMERAS, "camera"),
    "lens_id": (RefKind.LENSES, "lens"),
    "format_id": (RefKind.FORMATS, "format"),
    "film_id": (RefKind.FILMS, "film"),
    "developer_id": (RefKind.DEVELOPERS, "developer"),
    "filter_id": (RefKind.FILTERS, "filter"),
}


async def _check_refs(db: AsyncSession, data: dict[str, Any], current: Roll | None) -> None:
    """Every referenced item must exist, and archived ones may only be kept, not newly chosen."""
    for column, (kind, label) in REFS.items():
        item_id = data.get(column)
        if item_id is None or (current is not None and getattr(current, column) == item_id):
            continue
        item = await db.get(MODELS[kind], item_id)
        if item is None:
            raise InvalidReferenceError(f"Unknown {label}.")
        if item.archived_at is not None:
            raise InvalidReferenceError(f"The {label} '{item.name}' is archived.")


async def get_roll(db: AsyncSession, roll_id: uuid.UUID) -> Roll:
    roll = await db.get(Roll, roll_id)
    if roll is None:
        raise NotFoundError("No such roll.")
    return roll


async def create_roll(db: AsyncSession, actor: Principal, data: RollIn) -> Roll:
    values = data.model_dump()
    await _check_refs(db, values, None)
    roll = Roll(**values, created_by=actor.user_id, updated_by=actor.user_id)
    pair: Pair = (roll.film_id, roll.format_id)
    # A roll that counts against stock must have a roll to use; lock, write, then verify.
    before = await lock_pairs(db, [pair]) if roll.counts_against_stock else {}
    db.add(roll)
    await db.flush()
    if roll.counts_against_stock:
        await assert_non_negative(db, [pair], before)
    await db.commit()
    await db.refresh(roll)
    return roll


async def update_roll(
    db: AsyncSession, actor: Principal, roll_id: uuid.UUID, data: RollUpdate
) -> Roll:
    roll = await get_roll(db, roll_id)
    values = data.model_dump(exclude_unset=True)
    await _check_refs(db, values, roll)

    old_pair: Pair = (roll.film_id, roll.format_id)
    old_counts = roll.counts_against_stock
    new_pair: Pair = (
        values.get("film_id", roll.film_id),
        values.get("format_id", roll.format_id),
    )
    new_counts = values.get("counts_against_stock", old_counts)
    before = await lock_pairs(db, [old_pair, new_pair])

    for key, value in values.items():
        setattr(roll, key, value)
    roll.updated_by = actor.user_id
    await db.flush()
    # Stock only falls if the roll now counts against a pair it did not count against before.
    if new_counts and (not old_counts or new_pair != old_pair):
        await assert_non_negative(db, [new_pair], before)
    await db.commit()
    await db.refresh(roll)
    return roll


async def delete_roll(db: AsyncSession, actor: Principal, roll_id: uuid.UUID) -> None:
    roll = await get_roll(db, roll_id)
    await db.delete(roll)
    await db.commit()


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def list_rolls(db: AsyncSession, filters: RollFilters, page: Page) -> tuple[list[Roll], int]:
    """Matching rolls, newest first, and the total count ignoring pagination."""
    conditions = []
    if filters.date_from:
        conditions.append(Roll.dev_date >= filters.date_from)
    if filters.date_to:
        conditions.append(Roll.dev_date <= filters.date_to)
    if filters.film_id:
        conditions.append(Roll.film_id == filters.film_id)
    if filters.camera_id:
        conditions.append(Roll.camera_id == filters.camera_id)
    if filters.developer_id:
        conditions.append(Roll.developer_id == filters.developer_id)
    if filters.source:
        conditions.append(Roll.source == filters.source)
    if filters.q and filters.q.strip():
        pattern = _like_pattern(filters.q.strip())
        conditions.append(or_(Roll.subject.ilike(pattern), Roll.notes.ilike(pattern)))

    total = (
        await db.execute(select(func.count()).select_from(Roll).where(*conditions))
    ).scalar_one()
    rows = await db.execute(
        select(Roll)
        .where(*conditions)
        .order_by(Roll.dev_date.desc(), Roll.created_at.desc(), Roll.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(rows.unique().scalars()), total


async def last_roll_for_camera(db: AsyncSession, camera_id: uuid.UUID) -> Roll | None:
    """The camera's most recent roll by development date, used to prefill the log form."""
    rows = await db.execute(
        select(Roll)
        .where(Roll.camera_id == camera_id)
        .order_by(Roll.dev_date.desc(), Roll.created_at.desc())
        .limit(1)
    )
    return rows.unique().scalars().first()
