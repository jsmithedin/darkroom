import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base
from app.models.reference import Developer, Film


class DevTimeRef(AuditMixin, Base):
    """A hand-entered reference time for one film, EI and developer."""

    __tablename__ = "dev_time_refs"
    __table_args__ = (
        UniqueConstraint("film_id", "ei", "developer_id"),
        CheckConstraint("ei > 0", name="ei_positive"),
        CheckConstraint("minutes > 0", name="minutes_positive"),
    )

    film_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("films.id", ondelete="RESTRICT"))
    ei: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    developer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("developers.id", ondelete="RESTRICT")
    )
    minutes: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    film: Mapped[Film] = relationship(lazy="joined")
    developer: Mapped[Developer] = relationship(lazy="joined")
