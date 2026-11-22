import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import BulkRoll, Film, Format, StockMovement
from app.models.stock import stock_levels
from app.schemas.stock import (
    AdjustmentIn,
    BulkLoadIn,
    GivenAwayIn,
    MovementIn,
    MovementUpdate,
    OpeningIn,
    PurchaseIn,
)
from app.services.settings import get_settings
from app.services.units import cassette_mm


class NotFoundError(Exception):
    """No such movement, bulk roll, film or format."""


class InvalidMovementError(Exception):
    """The movement is not acceptable as submitted."""


class InsufficientStockError(Exception):
    """The write would leave fewer than zero rolls of a film in a format."""

    def __init__(
        self,
        film_id: uuid.UUID,
        format_id: uuid.UUID,
        film_name: str,
        format_name: str,
        available: int,
    ) -> None:
        self.film_id = film_id
        self.format_id = format_id
        self.film_name = film_name
        self.format_name = format_name
        self.available = available
        label = f"{film_name} {format_name}"
        if available > 0:
            message = f"Only {available} {label} in stock, not enough for this."
        else:
            message = f"No {label} in stock."
        super().__init__(f"{message} Record a purchase or a recount first.")


Pair = tuple[uuid.UUID, uuid.UUID]  # (film_id, format_id)


@dataclass(frozen=True)
class StockRow:
    film_id: uuid.UUID
    film_name: str
    film_type: str
    format_id: uuid.UUID
    format_name: str
    rolls: int


@dataclass(frozen=True)
class MovementFilters:
    film_id: uuid.UUID | None = None
    format_id: uuid.UUID | None = None
    kind: str | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class Page:
    limit: int = 50
    offset: int = 0


async def _require(
    db: AsyncSession, model: type[Film] | type[Format], item_id: uuid.UUID, label: str
) -> None:
    """The referenced film or format must exist."""
    if await db.get(model, item_id) is None:
        raise InvalidMovementError(f"Unknown {label}.")


async def current_stock(db: AsyncSession, film_id: uuid.UUID, format_id: uuid.UUID) -> int:
    """Rolls in stock for one film and format (0 when there is no history)."""
    level = (
        await db.execute(
            select(stock_levels.c.rolls).where(
                stock_levels.c.film_id == film_id, stock_levels.c.format_id == format_id
            )
        )
    ).scalar_one_or_none()
    return int(level or 0)


async def lock_pairs(db: AsyncSession, pairs: Iterable[Pair]) -> dict[Pair, int]:
    """Serialise writers on each (film, format) until this transaction ends.

    Locks are taken in sorted order so two writers touching the same pairs cannot deadlock.
    Returns the stock of each pair as it is under the lock, before this write changes anything.
    """
    ordered = sorted(set(pairs), key=lambda p: (str(p[0]), str(p[1])))
    before: dict[Pair, int] = {}
    for film_id, format_id in ordered:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"stock:{film_id}:{format_id}"},
        )
        before[(film_id, format_id)] = await current_stock(db, film_id, format_id)
    return before


async def assert_non_negative(
    db: AsyncSession, pairs: Iterable[Pair], before: dict[Pair, int] | None = None
) -> None:
    """Raise (after rolling back) if any pair is now below zero. Call after flushing the write,
    while holding the locks from `lock_pairs`."""
    for film_id, format_id in sorted(set(pairs), key=lambda p: (str(p[0]), str(p[1]))):
        if await current_stock(db, film_id, format_id) >= 0:
            continue
        film = await db.get(Film, film_id)
        fmt = await db.get(Format, format_id)
        names = (film.name if film else "film", fmt.name if fmt else "format")
        available = max(0, (before or {}).get((film_id, format_id), 0))
        await db.rollback()  # also releases the locks
        raise InsufficientStockError(film_id, format_id, names[0], names[1], available)


async def get_stock(db: AsyncSession, include_zero: bool = False) -> list[StockRow]:
    """Stock per film and format, grouped by film type then name."""
    stmt = (
        select(
            stock_levels.c.rolls,
            Film.id,
            Film.name,
            Film.type,
            Format.id,
            Format.name,
        )
        .join(Film, Film.id == stock_levels.c.film_id)
        .join(Format, Format.id == stock_levels.c.format_id)
        .order_by(Film.type, Film.name, Format.name)
    )
    if not include_zero:
        stmt = stmt.where(stock_levels.c.rolls != 0)
    rows = await db.execute(stmt)
    return [
        StockRow(f_id, f_name, f_type, fm_id, fm_name, int(n))
        for n, f_id, f_name, f_type, fm_id, fm_name in rows
    ]


async def get_movement(db: AsyncSession, movement_id: uuid.UUID) -> StockMovement:
    movement = await db.get(StockMovement, movement_id)
    if movement is None:
        raise NotFoundError("No such stock movement.")
    return movement


async def _save(
    db: AsyncSession,
    movement: StockMovement,
    guard: dict[Pair, int] | None = None,
    check: Iterable[Pair] = (),
) -> StockMovement:
    """Add and commit a movement; `check` pairs are verified non-negative before committing."""
    db.add(movement)
    await db.flush()
    await assert_non_negative(db, check, guard)
    await db.commit()
    await db.refresh(movement)
    return movement


async def record_purchase(db: AsyncSession, actor: Principal, data: PurchaseIn) -> StockMovement:
    await _require(db, Film, data.film_id, "film")
    await _require(db, Format, data.format_id, "format")
    return await _save(
        db,
        StockMovement(**data.model_dump(), created_by=actor.user_id, updated_by=actor.user_id),
    )


async def _format_35mm(db: AsyncSession) -> Format:
    fmt = (await db.execute(select(Format).where(Format.name == "35mm"))).scalar_one_or_none()
    if fmt is None:
        raise InvalidMovementError("There is no 35mm format; bulk film is loaded as 35mm.")
    return fmt


async def _bulk_metres(db: AsyncSession, rolls: int, exposures: int) -> int:
    """Film used by `rolls` cassettes, from the settings in force right now."""
    s = await get_settings(db)
    return rolls * cassette_mm(s.leader_mm, s.frame_pitch_mm, exposures)


async def record_bulk_load(db: AsyncSession, actor: Principal, data: BulkLoadIn) -> StockMovement:
    """Load cassettes from a spool. Stores a snapshot of the metres used (an estimate; settings
    changing later never alters it). Loading more than the spool holds is allowed."""
    bulk = await db.get(BulkRoll, data.bulk_roll_id)
    if bulk is None:
        raise InvalidMovementError("Unknown bulk roll.")
    fmt = await _format_35mm(db)
    values = data.model_dump(exclude={"bulk_roll_id"})
    return await _save(
        db,
        StockMovement(
            **values,
            bulk_roll_id=bulk.id,
            film_id=bulk.film_id,
            format_id=fmt.id,
            metres_mm=await _bulk_metres(db, data.rolls, data.exposures_per_cassette),
            created_by=actor.user_id,
            updated_by=actor.user_id,
        ),
    )


async def record_given_away(db: AsyncSession, actor: Principal, data: GivenAwayIn) -> StockMovement:
    await _require(db, Film, data.film_id, "film")
    await _require(db, Format, data.format_id, "format")
    pair = (data.film_id, data.format_id)
    before = await lock_pairs(db, [pair])
    return await _save(
        db,
        StockMovement(**data.model_dump(), created_by=actor.user_id, updated_by=actor.user_id),
        before,
        [pair],
    )


async def record_opening(db: AsyncSession, actor: Principal, data: OpeningIn) -> StockMovement:
    await _require(db, Film, data.film_id, "film")
    await _require(db, Format, data.format_id, "format")
    return await _save(
        db,
        StockMovement(**data.model_dump(), created_by=actor.user_id, updated_by=actor.user_id),
    )


async def record_adjustment(
    db: AsyncSession, actor: Principal, data: AdjustmentIn
) -> StockMovement:
    """Set stock to the counted figure: stores the delta now, and the figure for audit."""
    await _require(db, Film, data.film_id, "film")
    await _require(db, Format, data.format_id, "format")
    pair = (data.film_id, data.format_id)
    # Lock first so the delta is worked out against stock no one else is changing.
    before = await lock_pairs(db, [pair])
    delta = data.counted - before[pair]
    if delta == 0:
        await db.rollback()
        raise InvalidMovementError(f"Stock already shows {data.counted}; nothing to adjust.")
    return await _save(
        db,
        StockMovement(
            kind="adjustment",
            film_id=data.film_id,
            format_id=data.format_id,
            occurred_on=data.occurred_on,
            rolls=delta,
            counted_to=data.counted,
            notes=data.notes,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        ),
    )


async def create_movement(db: AsyncSession, actor: Principal, data: MovementIn) -> StockMovement:
    """Dispatch on the movement's kind."""
    if isinstance(data, PurchaseIn):
        return await record_purchase(db, actor, data)
    if isinstance(data, BulkLoadIn):
        return await record_bulk_load(db, actor, data)
    if isinstance(data, GivenAwayIn):
        return await record_given_away(db, actor, data)
    return await record_opening(db, actor, data)


# Fields each kind lets you change afterwards. An adjustment's delta was computed against the
# stock at the time, so only its date and notes are editable.
EDITABLE: dict[str, set[str]] = {
    "purchase": {"occurred_on", "notes", "film_id", "format_id", "rolls", "cost_pence", "supplier"},
    "bulk_load": {"occurred_on", "notes", "rolls", "exposures_per_cassette"},
    "given_away": {"occurred_on", "notes", "film_id", "format_id", "rolls"},
    "adjustment": {"occurred_on", "notes"},
    "opening": {"occurred_on", "notes", "film_id", "format_id", "rolls"},
}


async def update_movement(
    db: AsyncSession, actor: Principal, movement_id: uuid.UUID, data: MovementUpdate
) -> StockMovement:
    movement = await get_movement(db, movement_id)
    values = data.model_dump(exclude_unset=True)
    not_allowed = sorted(set(values) - EDITABLE[movement.kind])
    if not_allowed:
        raise InvalidMovementError(
            f"A {movement.kind.replace('_', ' ')} cannot change: {', '.join(not_allowed)}."
        )
    if "film_id" in values:
        await _require(db, Film, values["film_id"], "film")
    if "format_id" in values:
        await _require(db, Format, values["format_id"], "format")

    old_pair: Pair = (movement.film_id, movement.format_id)
    old_rolls = movement.rolls
    new_pair: Pair = (
        values.get("film_id", movement.film_id),
        values.get("format_id", movement.format_id),
    )
    before = await lock_pairs(db, [old_pair, new_pair])

    for key, value in values.items():
        setattr(movement, key, value)
    if movement.kind == "bulk_load" and ({"rolls", "exposures_per_cassette"} & set(values)):
        assert movement.exposures_per_cassette is not None
        movement.metres_mm = await _bulk_metres(db, movement.rolls, movement.exposures_per_cassette)
    movement.updated_by = actor.user_id

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidMovementError(
            "That change does not fit this kind of movement "
            "(for example, a purchase needs a positive number of rolls)."
        ) from exc
    await assert_non_negative(
        db, _reduced_pairs(old_pair, old_rolls, new_pair, movement.rolls), before
    )
    await db.commit()
    await db.refresh(movement)
    return movement


def _reduced_pairs(old_pair: Pair, old_rolls: int, new_pair: Pair, new_rolls: int) -> list[Pair]:
    """Pairs whose stock this edit can lower, so only those are checked."""
    if old_pair == new_pair:
        return [new_pair] if new_rolls < old_rolls else []
    pairs = []
    if old_rolls > 0:  # the old pair loses the rolls this movement used to add
        pairs.append(old_pair)
    if new_rolls < 0:  # the new pair now takes rolls out
        pairs.append(new_pair)
    return pairs


async def delete_movement(db: AsyncSession, actor: Principal, movement_id: uuid.UUID) -> None:
    movement = await get_movement(db, movement_id)
    pair: Pair = (movement.film_id, movement.format_id)
    before = await lock_pairs(db, [pair])
    removed = movement.rolls
    await db.delete(movement)
    await db.flush()
    if removed > 0:  # removing stock that was added (a purchase, a positive adjustment...)
        await assert_non_negative(db, [pair], before)
    await db.commit()


async def list_movements(
    db: AsyncSession, filters: MovementFilters, page: Page
) -> tuple[list[StockMovement], int]:
    conditions = []
    if filters.film_id:
        conditions.append(StockMovement.film_id == filters.film_id)
    if filters.format_id:
        conditions.append(StockMovement.format_id == filters.format_id)
    if filters.kind:
        conditions.append(StockMovement.kind == filters.kind)
    if filters.date_from:
        conditions.append(StockMovement.occurred_on >= filters.date_from)
    if filters.date_to:
        conditions.append(StockMovement.occurred_on <= filters.date_to)
    total = (
        await db.execute(select(func.count()).select_from(StockMovement).where(*conditions))
    ).scalar_one()
    rows = await db.execute(
        select(StockMovement)
        .where(*conditions)
        .order_by(StockMovement.occurred_on.desc(), StockMovement.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(rows.unique().scalars()), total
