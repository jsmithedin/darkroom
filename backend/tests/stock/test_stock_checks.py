"""The per-kind CHECK constraints, exercised directly against the database."""

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BulkRoll, Film, Format, StockMovement


async def seed(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    film = Film(name=f"Film {uuid.uuid4()}", type="bw", box_iso=400)
    fmt = Format(name=f"Format {uuid.uuid4()}")
    db.add_all([film, fmt])
    await db.flush()
    bulk = BulkRoll(label=f"Bulk {uuid.uuid4()}", film_id=film.id, length_mm=17_000)
    db.add(bulk)
    await db.flush()
    return film.id, fmt.id, bulk.id


def movement(film: uuid.UUID, fmt: uuid.UUID, **fields: Any) -> StockMovement:
    base: dict[str, Any] = {"film_id": film, "format_id": fmt, "occurred_on": date(2026, 11, 1)}
    return StockMovement(**(base | fields))


GOOD = {
    "purchase": {"kind": "purchase", "rolls": 5, "cost_pence": 1500, "supplier": "Shop"},
    "bulk_load": {
        "kind": "bulk_load",
        "rolls": 2,
        "exposures_per_cassette": 36,
        "metres_mm": 3236,
    },
    "given_away": {"kind": "given_away", "rolls": -1},
    "adjustment": {"kind": "adjustment", "rolls": 3, "counted_to": 10},
    "opening": {"kind": "opening", "rolls": 61},
}


@pytest.mark.parametrize("kind", list(GOOD))
async def test_well_formed_movement_of_every_kind_is_accepted(
    db_session: AsyncSession, kind: str
) -> None:
    film, fmt, bulk = await seed(db_session)
    fields = dict(GOOD[kind])
    if kind == "bulk_load":
        fields["bulk_roll_id"] = bulk
    db_session.add(movement(film, fmt, **fields))
    await db_session.flush()


BAD: list[tuple[str, dict[str, Any]]] = [
    ("purchase_without_cost_rejected", {**GOOD["purchase"], "cost_pence": None}),
    ("purchase_negative_cost_rejected", {**GOOD["purchase"], "cost_pence": -1}),
    ("purchase_with_exposures_rejected", {**GOOD["purchase"], "exposures_per_cassette": 36}),
    ("purchase_with_metres_rejected", {**GOOD["purchase"], "metres_mm": 100}),
    ("purchase_with_counted_to_rejected", {**GOOD["purchase"], "counted_to": 5}),
    ("purchase_negative_rolls_rejected", {**GOOD["purchase"], "rolls": -5}),
    ("bulk_load_without_bulk_roll_rejected", {**GOOD["bulk_load"]}),  # no bulk_roll_id
    ("bulk_load_without_exposures_rejected", {**GOOD["bulk_load"], "exposures_per_cassette": None}),
    ("bulk_load_without_metres_rejected", {**GOOD["bulk_load"], "metres_mm": None}),
    ("bulk_load_with_cost_rejected", {**GOOD["bulk_load"], "cost_pence": 100}),
    ("bulk_load_negative_rolls_rejected", {**GOOD["bulk_load"], "rolls": -2}),
    ("given_away_positive_rolls_rejected", {**GOOD["given_away"], "rolls": 1}),
    ("given_away_with_cost_rejected", {**GOOD["given_away"], "cost_pence": 100}),
    ("adjustment_without_counted_to_rejected", {**GOOD["adjustment"], "counted_to": None}),
    ("adjustment_negative_counted_to_rejected", {**GOOD["adjustment"], "counted_to": -1}),
    ("adjustment_with_supplier_rejected", {**GOOD["adjustment"], "supplier": "x"}),
    ("opening_negative_rejected", {**GOOD["opening"], "rolls": -1}),
    ("opening_with_counted_to_rejected", {**GOOD["opening"], "counted_to": 3}),
    ("zero_rolls_rejected", {**GOOD["adjustment"], "rolls": 0}),
    ("unknown_kind_rejected", {"kind": "gift", "rolls": 1}),
]


@pytest.mark.parametrize(("case", "fields"), BAD, ids=[c for c, _ in BAD])
async def test_check_constraints_reject(
    db_session: AsyncSession, case: str, fields: dict[str, Any]
) -> None:
    film, fmt, bulk = await seed(db_session)
    fields = dict(fields)
    if fields.get("kind") == "bulk_load" and "without_bulk_roll" not in case:
        fields["bulk_roll_id"] = bulk
    db_session.add(movement(film, fmt, **fields))
    with pytest.raises(IntegrityError):
        await db_session.flush()
