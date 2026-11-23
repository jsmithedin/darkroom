import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.rolls import DevTime, Ei, Number, Text
from app.schemas.stock import FilmRef


class NameRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class DevTimeRefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    film_id: uuid.UUID
    ei: Ei
    developer_id: uuid.UUID
    minutes: DevTime
    notes: Text | None = None


class DevTimeRefUpdate(BaseModel):
    """Only the fields sent change; only notes may be cleared with null."""

    model_config = ConfigDict(extra="forbid")

    film_id: uuid.UUID | None = None
    ei: Ei | None = None
    developer_id: uuid.UUID | None = None
    minutes: DevTime | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def no_null_required(self) -> "DevTimeRefUpdate":
        for name in ("film_id", "ei", "developer_id", "minutes"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DevTimeRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    film: FilmRef
    ei: Number
    developer: NameRef
    minutes: Number
    notes: str | None


class DevTimeEntry(BaseModel):
    roll_id: uuid.UUID
    dev_date: date
    minutes: Number


class DevTimeGroup(BaseModel):
    """Everything known for one film, EI and developer: logged times (newest first) and the
    hand-entered reference, if any."""

    film: FilmRef
    ei: Number
    developer: NameRef
    entries: list[DevTimeEntry]
    reference: DevTimeRefOut | None
