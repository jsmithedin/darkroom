from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.services import settings as svc

router = APIRouter(prefix="/api/settings", tags=["settings"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    leader_mm: int
    frame_pitch_mm: int
    timezone: str
    updated_at: datetime


class SettingsUpdate(BaseModel):
    """Only the fields sent change. Lengths are whole millimetres."""

    model_config = ConfigDict(extra="forbid")

    leader_mm: Annotated[int, Field(gt=0, le=10_000)] | None = None
    frame_pitch_mm: Annotated[int, Field(gt=0, le=1_000)] | None = None
    timezone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None


@router.get("")
async def read_settings(_: Reader, db: Db) -> SettingsOut:
    return SettingsOut.model_validate(await svc.get_settings(db))


@router.patch("")
async def patch_settings(body: SettingsUpdate, who: Writer, db: Db) -> SettingsOut:
    values = body.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()):
        raise HTTPException(status_code=422, detail="Settings values cannot be null.")
    try:
        row = await svc.update_settings(db, who, values)
    except svc.InvalidSettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SettingsOut.model_validate(row)
