import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    model_validator,
)

from app.services.units import format_stops, stops_vs_box

Source = Literal["factory", "bulk"]

# EI and development time are exact in the database; they go out as plain JSON numbers.
Ei = Annotated[Decimal, Field(gt=0, max_digits=7, decimal_places=2)]
DevTime = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=2)]
Number = Annotated[Decimal, PlainSerializer(lambda d: float(d), return_type=float)]
Text = Annotated[str, Field(max_length=5000)]

# Columns that cannot be cleared with an explicit null in a PATCH.
REQUIRED = ("dev_date", "camera_id", "format_id", "film_id", "ei", "developer_id", "source")


class RollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dev_date: date
    camera_id: uuid.UUID
    lens_id: uuid.UUID | None = None  # null = N/A
    format_id: uuid.UUID
    film_id: uuid.UUID
    ei: Ei
    developer_id: uuid.UUID
    dev_time_min: DevTime | None = None
    filter_id: uuid.UUID | None = None
    subject: Text | None = None
    notes: Text | None = None
    source: Source = "factory"
    counts_against_stock: bool = True


class RollUpdate(BaseModel):
    """Every field optional; only the ones sent change. Nullable fields accept null to clear."""

    model_config = ConfigDict(extra="forbid")

    dev_date: date | None = None
    camera_id: uuid.UUID | None = None
    lens_id: uuid.UUID | None = None
    format_id: uuid.UUID | None = None
    film_id: uuid.UUID | None = None
    ei: Ei | None = None
    developer_id: uuid.UUID | None = None
    dev_time_min: DevTime | None = None
    filter_id: uuid.UUID | None = None
    subject: Text | None = None
    notes: Text | None = None
    source: Source | None = None
    counts_against_stock: bool | None = None

    @model_validator(mode="after")
    def no_null_required(self) -> "RollUpdate":
        for name in (*REQUIRED, "counts_against_stock"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class RefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class FilmRefOut(RefOut):
    type: str
    box_iso: int


class RollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dev_date: date
    camera: RefOut
    lens: RefOut | None
    format: RefOut
    film: FilmRefOut
    ei: Number
    developer: RefOut
    dev_time_min: Number | None
    filter: RefOut | None
    subject: str | None
    notes: str | None
    source: str
    counts_against_stock: bool

    # Derived on the way out; nothing below is stored.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def year(self) -> int:
        return self.dev_date.year

    @computed_field  # type: ignore[prop-decorator]
    @property
    def month(self) -> int:
        return self.dev_date.month

    @computed_field  # type: ignore[prop-decorator]
    @property
    def film_type(self) -> str:
        return self.film.type

    @computed_field  # type: ignore[prop-decorator]
    @property
    def box_iso(self) -> int:
        return self.film.box_iso

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stops_vs_box(self) -> str:
        return format_stops(stops_vs_box(self.ei, self.film.box_iso))


class RollPage(BaseModel):
    items: list[RollOut]
    total: int
    limit: int
    offset: int
