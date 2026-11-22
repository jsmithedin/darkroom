import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.models.reference import Camera
from app.schemas.rolls import RollIn, RollOut, RollPage, RollUpdate
from app.services import rolls as svc

router = APIRouter(prefix="/api", tags=["rolls"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


@router.get("/rolls")
async def list_rolls(
    _: Reader,
    db: Db,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    film: uuid.UUID | None = None,
    camera: uuid.UUID | None = None,
    developer: uuid.UUID | None = None,
    source: Literal["factory", "bulk"] | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RollPage:
    filters = svc.RollFilters(date_from, date_to, film, camera, developer, source, q)
    rolls, total = await svc.list_rolls(db, filters, svc.Page(limit, offset))
    return RollPage(
        items=[RollOut.model_validate(r) for r in rolls], total=total, limit=limit, offset=offset
    )


@router.post("/rolls", status_code=201)
async def create_roll(body: RollIn, who: Writer, db: Db) -> RollOut:
    try:
        roll = await svc.create_roll(db, who, body)
    except svc.InvalidReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RollOut.model_validate(roll)


@router.get("/rolls/{roll_id}")
async def get_roll(roll_id: uuid.UUID, _: Reader, db: Db) -> RollOut:
    try:
        return RollOut.model_validate(await svc.get_roll(db, roll_id))
    except svc.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/rolls/{roll_id}")
async def update_roll(roll_id: uuid.UUID, body: RollUpdate, who: Writer, db: Db) -> RollOut:
    try:
        roll = await svc.update_roll(db, who, roll_id, body)
    except svc.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except svc.InvalidReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RollOut.model_validate(roll)


@router.delete("/rolls/{roll_id}", status_code=204)
async def delete_roll(roll_id: uuid.UUID, who: Writer, db: Db) -> Response:
    try:
        await svc.delete_roll(db, who, roll_id)
    except svc.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/cameras/{camera_id}/last-roll")
async def last_roll(camera_id: uuid.UUID, _: Reader, db: Db) -> RollOut:
    """Most recent roll for the camera, so the log form can prefill lens and format."""
    if await db.get(Camera, camera_id) is None:
        raise HTTPException(status_code=404, detail="No such camera.")
    roll = await svc.last_roll_for_camera(db, camera_id)
    if roll is None:
        raise HTTPException(status_code=404, detail="No rolls logged for this camera yet.")
    return RollOut.model_validate(roll)
