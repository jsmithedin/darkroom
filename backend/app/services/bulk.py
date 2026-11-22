import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import BulkRoll, Film, StockMovement
from app.schemas.bulk import BulkRollIn, BulkRollOut, BulkRollUpdate
from app.schemas.stock import FilmRef
from app.services.settings import get_settings
from app.services.units import bulk_derived


class NotFoundError(Exception):
    """No such bulk roll."""


class InvalidBulkRollError(Exception):
    """The bulk roll is not acceptable as submitted (unknown film, bad change)."""


class ConflictError(Exception):
    """The label is taken, or the spool has loads that block the change."""


Loads = list[tuple[int, int]]  # (rolls, metres_mm snapshot) for each cassette load


def _out(bulk: BulkRoll, loads: Loads, leader_mm: int, pitch_mm: int) -> BulkRollOut:
    derived = bulk_derived(
        bulk.length_mm, bulk.cost_pence, bulk.used_before_mm, loads, leader_mm, pitch_mm
    )
    return BulkRollOut(
        id=bulk.id,
        label=bulk.label,
        film=FilmRef.model_validate(bulk.film),
        length_mm=bulk.length_mm,
        cost_pence=bulk.cost_pence,
        supplier=bulk.supplier,
        bought_on=bulk.bought_on,
        used_before_mm=bulk.used_before_mm,
        finished=bulk.finished,
        notes=bulk.notes,
        created_at=bulk.created_at,
        cassettes_loaded=derived.cassettes_loaded,
        used_mm=derived.used_mm,
        left_mm=derived.left_mm,
        exposures_left=derived.exposures_left,
        cost_per_36_pence=derived.cost_per_36_pence,
    )


async def _loads(db: AsyncSession, bulk_ids: list[uuid.UUID]) -> dict[uuid.UUID, Loads]:
    """Each spool's loads as (rolls, metres_mm snapshots)."""
    grouped: dict[uuid.UUID, Loads] = defaultdict(list)
    if not bulk_ids:
        return grouped
    rows = await db.execute(
        select(StockMovement.bulk_roll_id, StockMovement.rolls, StockMovement.metres_mm).where(
            StockMovement.kind == "bulk_load", StockMovement.bulk_roll_id.in_(bulk_ids)
        )
    )
    for bulk_id, rolls, metres in rows:
        if bulk_id is not None and metres is not None:  # always set for a bulk load
            grouped[bulk_id].append((rolls, metres))
    return grouped


async def get_bulk_rolls(db: AsyncSession, include_finished: bool = True) -> list[BulkRollOut]:
    """Every spool with its derived figures, unfinished first."""
    stmt = select(BulkRoll).order_by(BulkRoll.finished, BulkRoll.label)
    if not include_finished:
        stmt = stmt.where(BulkRoll.finished.is_(False))
    spools = list((await db.execute(stmt)).unique().scalars())
    loads = await _loads(db, [b.id for b in spools])
    s = await get_settings(db)
    return [_out(b, loads[b.id], s.leader_mm, s.frame_pitch_mm) for b in spools]


async def _get(db: AsyncSession, bulk_id: uuid.UUID) -> BulkRoll:
    bulk = await db.get(BulkRoll, bulk_id)
    if bulk is None:
        raise NotFoundError("No such bulk roll.")
    return bulk


async def get_bulk_roll(db: AsyncSession, bulk_id: uuid.UUID) -> BulkRollOut:
    bulk = await _get(db, bulk_id)
    loads = await _loads(db, [bulk.id])
    s = await get_settings(db)
    return _out(bulk, loads[bulk.id], s.leader_mm, s.frame_pitch_mm)


async def _check_label_free(db: AsyncSession, label: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(BulkRoll.id).where(BulkRoll.label == label)
    if exclude is not None:
        stmt = stmt.where(BulkRoll.id != exclude)
    if (await db.execute(stmt)).first() is not None:
        raise ConflictError(f"A bulk roll labelled '{label}' already exists.")


async def _commit(db: AsyncSession, label: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:  # lost a race on the unique label
        await db.rollback()
        raise ConflictError(f"A bulk roll labelled '{label}' already exists.") from exc


async def create_bulk_roll(db: AsyncSession, actor: Principal, data: BulkRollIn) -> BulkRollOut:
    if await db.get(Film, data.film_id) is None:
        raise InvalidBulkRollError("Unknown film.")
    await _check_label_free(db, data.label)
    bulk = BulkRoll(**data.model_dump(), created_by=actor.user_id, updated_by=actor.user_id)
    db.add(bulk)
    await db.flush()
    bulk_id = bulk.id
    await _commit(db, data.label)
    db.expunge_all()  # reload with the film joined, rather than touching a half-loaded object
    return await get_bulk_roll(db, bulk_id)


async def update_bulk_roll(
    db: AsyncSession, actor: Principal, bulk_id: uuid.UUID, data: BulkRollUpdate
) -> BulkRollOut:
    bulk = await _get(db, bulk_id)
    values: dict[str, Any] = data.model_dump(exclude_unset=True)
    if "label" in values:
        await _check_label_free(db, values["label"], exclude=bulk.id)
    if "film_id" in values and values["film_id"] != bulk.film_id:
        if await db.get(Film, values["film_id"]) is None:
            raise InvalidBulkRollError("Unknown film.")
        if (await _loads(db, [bulk.id]))[bulk.id]:
            raise ConflictError(
                "The film cannot change once cassettes have been loaded from this spool."
            )
    for key, value in values.items():
        setattr(bulk, key, value)
    bulk.updated_by = actor.user_id
    await _commit(db, values.get("label", bulk.label))
    db.expunge_all()  # the film relationship may have changed; reload it
    return await get_bulk_roll(db, bulk_id)


async def delete_bulk_roll(db: AsyncSession, actor: Principal, bulk_id: uuid.UUID) -> None:
    bulk = await _get(db, bulk_id)
    loads = (await _loads(db, [bulk.id]))[bulk.id]
    if loads:
        raise ConflictError(
            f"'{bulk.label}' has {len(loads)} cassette load(s) recorded against it. "
            "Mark it finished instead, or delete those loads first."
        )
    await db.delete(bulk)
    await db.commit()
