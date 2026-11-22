import enum
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, false, true
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base


class RefKind(enum.StrEnum):
    """The six reference tables; the value is also the URL segment."""

    CAMERAS = "cameras"
    LENSES = "lenses"
    DEVELOPERS = "developers"
    FILTERS = "filters"
    FILMS = "films"
    FORMATS = "formats"


class NamedItem(AuditMixin, Base):
    __abstract__ = True

    """Common shape: a unique, case-insensitive name that can be archived but never deleted."""

    name: Mapped[str] = mapped_column(CITEXT, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Format(NamedItem):
    __tablename__ = "formats"


class Camera(NamedItem):
    __tablename__ = "cameras"

    fixed_lens: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class Lens(NamedItem):
    __tablename__ = "lenses"


class Developer(NamedItem):
    __tablename__ = "developers"


class Filter(NamedItem):
    __tablename__ = "filters"


FILM_TYPES = ("bw", "colour", "slide")


class Film(NamedItem):
    __tablename__ = "films"
    __table_args__ = (
        CheckConstraint("type in ('bw', 'colour', 'slide')", name="type"),
        CheckConstraint("box_iso > 0", name="box_iso_positive"),
    )

    type: Mapped[str] = mapped_column(String)
    box_iso: Mapped[int] = mapped_column(Integer)


class AppSettings(AuditMixin, Base):
    """The single settings row (table `settings`). Bulk maths and the display timezone."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("singleton", name="singleton"),
        CheckConstraint("leader_mm > 0", name="leader_mm_positive"),
        CheckConstraint("frame_pitch_mm > 0", name="frame_pitch_mm_positive"),
    )

    singleton: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), unique=True
    )
    leader_mm: Mapped[int] = mapped_column(Integer, default=250, server_default="250")
    frame_pitch_mm: Mapped[int] = mapped_column(Integer, default=38, server_default="38")
    timezone: Mapped[str] = mapped_column(
        String, default="Europe/London", server_default="Europe/London"
    )


MODELS: dict[RefKind, type[NamedItem]] = {
    RefKind.CAMERAS: Camera,
    RefKind.LENSES: Lens,
    RefKind.DEVELOPERS: Developer,
    RefKind.FILTERS: Filter,
    RefKind.FILMS: Film,
    RefKind.FORMATS: Format,
}
