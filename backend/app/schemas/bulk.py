import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.stock import FilmRef

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Length = Annotated[int, Field(gt=0, le=1_000_000)]  # millimetres; 1 km is plenty
Pence = Annotated[int, Field(ge=0, le=100_000_000)]
Used = Annotated[int, Field(ge=0, le=1_000_000)]
Text = Annotated[str, Field(max_length=2000)]

# Columns that cannot be cleared with an explicit null.
REQUIRED = ("label", "film_id", "length_mm", "used_before_mm", "finished")


class BulkRollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Label
    film_id: uuid.UUID
    length_mm: Length
    cost_pence: Pence | None = None  # unpriced spools are fine
    supplier: Text | None = None
    bought_on: date | None = None
    used_before_mm: Used = 0  # film used before tracking began
    finished: bool = False
    notes: Text | None = None


class BulkRollUpdate(BaseModel):
    """Only the fields sent change; nullable ones accept null to clear."""

    model_config = ConfigDict(extra="forbid")

    label: Label | None = None
    film_id: uuid.UUID | None = None
    length_mm: Length | None = None
    cost_pence: Pence | None = None
    supplier: Text | None = None
    bought_on: date | None = None
    used_before_mm: Used | None = None
    finished: bool | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def no_null_required(self) -> "BulkRollUpdate":
        for name in REQUIRED:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class BulkRollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    film: FilmRef
    length_mm: int
    cost_pence: int | None
    supplier: str | None
    bought_on: date | None
    used_before_mm: int
    finished: bool
    notes: str | None
    created_at: datetime

    # Derived from the loads and the current settings; never stored.
    cassettes_loaded: int
    used_mm: int
    left_mm: int
    exposures_left: int
    cost_per_36_pence: int | None
