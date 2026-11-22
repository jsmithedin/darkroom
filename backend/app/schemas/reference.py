import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FilmType = Literal["bw", "colour", "slide"]
BoxIso = Annotated[int, Field(gt=0, le=102400)]


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NamedCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class NamedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None


class CameraCreate(NamedCreate):
    fixed_lens: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class CameraUpdate(NamedUpdate):
    fixed_lens: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CameraOut(ItemOut):
    fixed_lens: bool
    notes: str | None


class FilmCreate(NamedCreate):
    type: FilmType
    box_iso: BoxIso


class FilmUpdate(NamedUpdate):
    type: FilmType | None = None
    box_iso: BoxIso | None = None


class FilmOut(ItemOut):
    type: str
    box_iso: int
