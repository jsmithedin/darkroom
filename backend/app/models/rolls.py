import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base
from app.models.reference import Camera, Developer, Film, Filter, Format, Lens

SOURCES = ("factory", "bulk")


class Roll(AuditMixin, Base):
    """One developed roll. Year, month, film type, box ISO and stops are derived, never stored."""

    __tablename__ = "rolls"
    __table_args__ = (
        CheckConstraint("ei > 0", name="ei_positive"),
        CheckConstraint("dev_time_min IS NULL OR dev_time_min > 0", name="dev_time_positive"),
        CheckConstraint("source in ('factory', 'bulk')", name="source"),
        Index("ix_rolls_dev_date", "dev_date"),
        Index("ix_rolls_film_ei_developer", "film_id", "ei", "developer_id"),
        Index("ix_rolls_camera_dev_date", "camera_id", "dev_date"),
    )

    dev_date: Mapped[date] = mapped_column(Date)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id", ondelete="RESTRICT"))
    lens_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lenses.id", ondelete="RESTRICT"), default=None
    )  # null means N/A (fixed-lens camera)
    format_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("formats.id", ondelete="RESTRICT"))
    film_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("films.id", ondelete="RESTRICT"))
    ei: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    developer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("developers.id", ondelete="RESTRICT")
    )
    dev_time_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=None)
    filter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("filters.id", ondelete="RESTRICT"), default=None
    )
    subject: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[str] = mapped_column(String, default="factory", server_default="factory")
    counts_against_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    camera: Mapped[Camera] = relationship(lazy="joined")
    lens: Mapped[Lens | None] = relationship(lazy="joined")
    format: Mapped[Format] = relationship(lazy="joined")
    film: Mapped[Film] = relationship(lazy="joined")
    developer: Mapped[Developer] = relationship(lazy="joined")
    filter: Mapped[Filter | None] = relationship(lazy="joined")
