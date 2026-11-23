from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, Principal, require_scope
from app.db import get_session
from app.schemas.stats import CameraIdle, SpendYear, Stats
from app.services import stats as svc
from app.services.settings import get_settings

router = APIRouter(prefix="/api/stats", tags=["stats"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Db = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def read_stats(
    _: Reader, db: Db, year: Annotated[int | None, Query(ge=1900, le=2200)] = None
) -> Stats:
    settings = await get_settings(db)
    today = svc.london_today(datetime.now(UTC), settings.timezone)
    return await svc.get_stats(db, today.year if year is None else year, today)


@router.get("/camera-idle")
async def read_camera_idle(_: Reader, db: Db) -> list[CameraIdle]:
    return await svc.camera_idle(db)


@router.get("/spend")
async def read_spend(_: Reader, db: Db) -> list[SpendYear]:
    return await svc.spend(db)
