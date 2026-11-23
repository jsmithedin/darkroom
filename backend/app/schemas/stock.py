import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Notes = Annotated[str, Field(max_length=2000)]
Supplier = Annotated[str, Field(max_length=200)]
Rolls = Annotated[int, Field(le=10_000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PurchaseIn(_In):
    kind: Literal["purchase"]
    film_id: uuid.UUID
    format_id: uuid.UUID
    occurred_on: date
    rolls: Annotated[int, Field(gt=0, le=10_000)]
    cost_pence: Annotated[int, Field(ge=0, le=100_000_000)]  # receipt total
    supplier: Supplier | None = None
    notes: Notes | None = None


class BulkLoadIn(_In):
    """Cassettes loaded from a bulk spool. Film and format (35mm) come from the spool."""

    kind: Literal["bulk_load"]
    bulk_roll_id: uuid.UUID
    occurred_on: date
    rolls: Annotated[int, Field(gt=0, le=1_000)]
    exposures_per_cassette: Annotated[int, Field(gt=0, le=100)]
    notes: Notes | None = None


class GivenAwayIn(_In):
    """`rolls` is negative: the change to stock."""

    kind: Literal["given_away"]
    film_id: uuid.UUID
    format_id: uuid.UUID
    occurred_on: date
    rolls: Annotated[int, Field(lt=0, ge=-10_000)]
    notes: Notes | None = None


class OpeningIn(_In):
    kind: Literal["opening"]
    film_id: uuid.UUID
    format_id: uuid.UUID
    occurred_on: date
    rolls: Annotated[int, Field(gt=0, le=10_000)]
    notes: Notes | None = None


MovementIn = Annotated[
    PurchaseIn | BulkLoadIn | GivenAwayIn | OpeningIn, Field(discriminator="kind")
]


class AdjustmentIn(_In):
    """Set stock to a counted figure; the change is worked out on the server."""

    film_id: uuid.UUID
    format_id: uuid.UUID
    counted: Annotated[int, Field(ge=0, le=100_000)]
    occurred_on: date
    notes: Notes | None = None


class CountIn(_In):
    film_id: uuid.UUID
    format_id: uuid.UUID
    counted: Annotated[int, Field(ge=0, le=100_000)]
    expected: Annotated[int, Field(ge=-100_000, le=100_000)]  # the recorded balance reviewed


class StocktakeIn(_In):
    """Several counts reviewed together. `batch_id` is chosen by the client once per review, so a
    retry of the same request applies nothing twice."""

    batch_id: uuid.UUID
    occurred_on: date
    notes: Notes | None = None
    counts: Annotated[list[CountIn], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def _distinct_pairs(self) -> "StocktakeIn":
        pairs = [(c.film_id, c.format_id) for c in self.counts]
        if len(set(pairs)) != len(pairs):
            raise ValueError("each film and format can be counted once")
        return self


class MovementUpdate(_In):
    """Only fields that make sense for the movement's kind are accepted (checked by the service)."""

    occurred_on: date | None = None
    notes: Notes | None = None
    film_id: uuid.UUID | None = None
    format_id: uuid.UUID | None = None
    rolls: Annotated[int, Field(ge=-10_000, le=10_000)] | None = None
    cost_pence: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    supplier: Supplier | None = None
    exposures_per_cassette: Annotated[int, Field(gt=0, le=100)] | None = None

    @model_validator(mode="after")
    def no_null_required(self) -> "MovementUpdate":
        for name in ("occurred_on", "film_id", "format_id", "rolls", "cost_pence"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class FilmRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str


class FormatRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    film: FilmRef
    format: FormatRef
    occurred_on: date
    rolls: int
    notes: str | None
    cost_pence: int | None
    supplier: str | None
    bulk_roll_id: uuid.UUID | None
    exposures_per_cassette: int | None
    metres_mm: int | None
    counted_to: int | None
    created_at: datetime


class MovementPage(BaseModel):
    items: list[MovementOut]
    total: int
    limit: int
    offset: int


class StockRowOut(BaseModel):
    film: FilmRef
    format: FormatRef
    rolls: int
