import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    column,
    false,
    table,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base
from app.models.reference import Film, Format

KINDS = ("purchase", "bulk_load", "given_away", "adjustment", "opening")

# Columns that belong to one kind only; every other kind must leave them null.
_NONE = {
    "cost": "cost_pence IS NULL",
    "supplier": "supplier IS NULL",
    "bulk": "bulk_roll_id IS NULL",
    "exposures": "exposures_per_cassette IS NULL",
    "metres": "metres_mm IS NULL",
    "counted": "counted_to IS NULL",
}


def _nulls(*names: str) -> str:
    return " AND ".join(_NONE[n] for n in names)


class BulkRoll(AuditMixin, Base):
    """A spool of film bought in bulk and wound into cassettes."""

    __tablename__ = "bulk_rolls"
    __table_args__ = (
        CheckConstraint("length_mm > 0", name="length_positive"),
        CheckConstraint("cost_pence IS NULL OR cost_pence >= 0", name="cost_non_negative"),
        CheckConstraint("used_before_mm >= 0", name="used_before_non_negative"),
    )

    label: Mapped[str] = mapped_column(CITEXT, unique=True)
    film_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("films.id", ondelete="RESTRICT"))
    length_mm: Mapped[int] = mapped_column(Integer)
    cost_pence: Mapped[int | None] = mapped_column(Integer, default=None)
    supplier: Mapped[str | None] = mapped_column(Text, default=None)
    bought_on: Mapped[date | None] = mapped_column(Date, default=None)
    used_before_mm: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    finished: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    film: Mapped[Film] = relationship(lazy="joined")


class StockMovement(AuditMixin, Base):
    """A signed change to the number of rolls held of one film in one format."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(f"kind in ({', '.join(repr(k) for k in KINDS)})", name="kind"),
        CheckConstraint("rolls <> 0", name="rolls_non_zero"),
        # One constraint per kind: required fields present, other kinds' fields null.
        CheckConstraint(
            "kind <> 'purchase' OR (rolls > 0 AND cost_pence IS NOT NULL AND cost_pence >= 0 AND "
            + _nulls("bulk", "exposures", "metres", "counted")
            + ")",
            name="purchase_shape",
        ),
        CheckConstraint(
            "kind <> 'bulk_load' OR (rolls > 0 AND bulk_roll_id IS NOT NULL AND "
            "exposures_per_cassette IS NOT NULL AND exposures_per_cassette > 0 AND "
            "metres_mm IS NOT NULL AND metres_mm > 0 AND "
            + _nulls("cost", "supplier", "counted")
            + ")",
            name="bulk_load_shape",
        ),
        CheckConstraint(
            "kind <> 'given_away' OR (rolls < 0 AND "
            + _nulls("cost", "supplier", "bulk", "exposures", "metres", "counted")
            + ")",
            name="given_away_shape",
        ),
        CheckConstraint(
            "kind <> 'adjustment' OR (counted_to IS NOT NULL AND counted_to >= 0 AND "
            + _nulls("cost", "supplier", "bulk", "exposures", "metres")
            + ")",
            name="adjustment_shape",
        ),
        CheckConstraint(
            "kind <> 'opening' OR (rolls > 0 AND "
            + _nulls("cost", "supplier", "bulk", "exposures", "metres", "counted")
            + ")",
            name="opening_shape",
        ),
        Index("ix_stock_movements_film_format", "film_id", "format_id"),
        Index("ix_stock_movements_count_batch", "count_batch_id"),
        Index("ix_stock_movements_occurred_on", "occurred_on"),
    )

    film_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("films.id", ondelete="RESTRICT"))
    format_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("formats.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String)
    occurred_on: Mapped[date] = mapped_column(Date)
    rolls: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    cost_pence: Mapped[int | None] = mapped_column(Integer, default=None)
    supplier: Mapped[str | None] = mapped_column(Text, default=None)
    bulk_roll_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bulk_rolls.id", ondelete="RESTRICT"), default=None
    )
    exposures_per_cassette: Mapped[int | None] = mapped_column(Integer, default=None)
    metres_mm: Mapped[int | None] = mapped_column(Integer, default=None)
    counted_to: Mapped[int | None] = mapped_column(Integer, default=None)
    # Set on adjustments made by one stocktake; a retry of the same batch finds them and stops.
    count_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)

    film: Mapped[Film] = relationship(lazy="joined")
    format: Mapped[Format] = relationship(lazy="joined")


# Read-only view: movements minus rolls that count against stock (created in migration 0006).
stock_levels = table(
    "stock_levels",
    column("film_id", Uuid),
    column("format_id", Uuid),
    column("rolls", Integer),
)

STOCK_LEVELS_SQL = """
CREATE VIEW stock_levels AS
SELECT film_id, format_id, SUM(rolls)::int AS rolls
FROM (
    SELECT film_id, format_id, rolls FROM stock_movements
    UNION ALL
    SELECT film_id, format_id, -1 FROM rolls WHERE counts_against_stock
) AS movements
GROUP BY film_id, format_id
"""
