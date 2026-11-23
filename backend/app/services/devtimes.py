import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import Developer, DevTimeRef, Film, Roll
from app.schemas.devtimes import (
    DevTimeEntry,
    DevTimeGroup,
    DevTimeRefIn,
    DevTimeRefOut,
    DevTimeRefUpdate,
    NameRef,
)
from app.schemas.stock import FilmRef


class NotFoundError(Exception):
    """No such reference time."""


class InvalidRefError(Exception):
    """Unknown film or developer."""


class ConflictError(Exception):
    """A reference for that film, EI and developer already exists."""


Key = tuple[uuid.UUID, Decimal, uuid.UUID]


async def grouped_dev_times(
    db: AsyncSession,
    film_id: uuid.UUID | None = None,
    ei: Decimal | None = None,
    developer_id: uuid.UUID | None = None,
) -> list[DevTimeGroup]:
    """Logged times grouped by film, EI and developer (newest first; rolls with no time are
    left out), each with its reference time. A reference with no logged roll still appears."""
    roll_stmt = select(Roll).where(Roll.dev_time_min.is_not(None))
    ref_stmt = select(DevTimeRef)
    for col_roll, col_ref, value in (
        (Roll.film_id, DevTimeRef.film_id, film_id),
        (Roll.ei, DevTimeRef.ei, ei),
        (Roll.developer_id, DevTimeRef.developer_id, developer_id),
    ):
        if value is not None:
            roll_stmt = roll_stmt.where(col_roll == value)
            ref_stmt = ref_stmt.where(col_ref == value)
    rolls = (
        (await db.execute(roll_stmt.order_by(Roll.dev_date.desc(), Roll.created_at.desc())))
        .unique()
        .scalars()
    )
    refs = (await db.execute(ref_stmt)).unique().scalars()

    groups: dict[Key, DevTimeGroup] = {}

    def group(film: Film, e: Decimal, dev: Developer) -> DevTimeGroup:
        key = (film.id, e, dev.id)
        if key not in groups:
            groups[key] = DevTimeGroup(
                film=FilmRef.model_validate(film),
                ei=e,
                developer=NameRef.model_validate(dev),
                entries=[],
                reference=None,
            )
        return groups[key]

    for roll in rolls:
        assert roll.dev_time_min is not None
        group(roll.film, roll.ei, roll.developer).entries.append(
            DevTimeEntry(roll_id=roll.id, dev_date=roll.dev_date, minutes=roll.dev_time_min)
        )
    for ref in refs:
        group(ref.film, ref.ei, ref.developer).reference = DevTimeRefOut.model_validate(ref)
    return sorted(groups.values(), key=lambda g: (g.film.name.casefold(), g.ei, g.developer.name))


async def list_refs(db: AsyncSession) -> list[DevTimeRefOut]:
    rows = (await db.execute(select(DevTimeRef))).unique().scalars()
    out = [DevTimeRefOut.model_validate(r) for r in rows]
    return sorted(out, key=lambda r: (r.film.name.casefold(), r.ei, r.developer.name))


async def _get(db: AsyncSession, ref_id: uuid.UUID) -> DevTimeRef:
    ref = await db.get(DevTimeRef, ref_id)
    if ref is None:
        raise NotFoundError("No such reference time.")
    return ref


async def _check_ids(db: AsyncSession, film_id: uuid.UUID, developer_id: uuid.UUID) -> None:
    if await db.get(Film, film_id) is None:
        raise InvalidRefError("Unknown film.")
    if await db.get(Developer, developer_id) is None:
        raise InvalidRefError("Unknown developer.")


async def _exists(db: AsyncSession, key: Key, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(DevTimeRef.id).where(
        DevTimeRef.film_id == key[0], DevTimeRef.ei == key[1], DevTimeRef.developer_id == key[2]
    )
    if exclude is not None:
        stmt = stmt.where(DevTimeRef.id != exclude)
    return (await db.execute(stmt)).first() is not None


CONFLICT = "A reference time for that film, EI and developer already exists."


async def _reload(db: AsyncSession, ref_id: uuid.UUID) -> DevTimeRefOut:
    db.expunge_all()
    return DevTimeRefOut.model_validate(await _get(db, ref_id))


async def create_ref(db: AsyncSession, actor: Principal, data: DevTimeRefIn) -> DevTimeRefOut:
    await _check_ids(db, data.film_id, data.developer_id)
    if await _exists(db, (data.film_id, data.ei, data.developer_id)):
        raise ConflictError(CONFLICT)
    ref = DevTimeRef(**data.model_dump(), created_by=actor.user_id, updated_by=actor.user_id)
    db.add(ref)
    await db.flush()
    ref_id = ref.id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(CONFLICT) from exc
    return await _reload(db, ref_id)


async def update_ref(
    db: AsyncSession, actor: Principal, ref_id: uuid.UUID, data: DevTimeRefUpdate
) -> DevTimeRefOut:
    ref = await _get(db, ref_id)
    values: dict[str, Any] = data.model_dump(exclude_unset=True)
    film_id = values.get("film_id", ref.film_id)
    developer_id = values.get("developer_id", ref.developer_id)
    ei = values.get("ei", ref.ei)
    await _check_ids(db, film_id, developer_id)
    if await _exists(db, (film_id, ei, developer_id), exclude=ref.id):
        raise ConflictError(CONFLICT)
    for key, value in values.items():
        setattr(ref, key, value)
    ref.updated_by = actor.user_id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(CONFLICT) from exc
    return await _reload(db, ref_id)


async def delete_ref(db: AsyncSession, ref_id: uuid.UUID) -> None:
    await db.delete(await _get(db, ref_id))
    await db.commit()
