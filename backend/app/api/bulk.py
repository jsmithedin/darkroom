import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.schemas.bulk import BulkRollIn, BulkRollOut, BulkRollUpdate
from app.services import bulk as svc

router = APIRouter(prefix="/api/bulk-rolls", tags=["bulk-rolls"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
async def list_bulk_rolls(_: Reader, db: Db, include_finished: bool = True) -> list[BulkRollOut]:
    return await svc.get_bulk_rolls(db, include_finished)


@router.post("", status_code=201)
async def create_bulk_roll(body: BulkRollIn, who: Writer, db: Db) -> BulkRollOut:
    try:
        return await svc.create_bulk_roll(db, who, body)
    except (svc.InvalidBulkRollError, svc.ConflictError) as exc:
        raise _http(exc) from exc


@router.get("/{bulk_id}")
async def get_bulk_roll(bulk_id: uuid.UUID, _: Reader, db: Db) -> BulkRollOut:
    try:
        return await svc.get_bulk_roll(db, bulk_id)
    except svc.NotFoundError as exc:
        raise _http(exc) from exc


@router.patch("/{bulk_id}")
async def update_bulk_roll(
    bulk_id: uuid.UUID, body: BulkRollUpdate, who: Writer, db: Db
) -> BulkRollOut:
    try:
        return await svc.update_bulk_roll(db, who, bulk_id, body)
    except (svc.NotFoundError, svc.InvalidBulkRollError, svc.ConflictError) as exc:
        raise _http(exc) from exc


@router.delete("/{bulk_id}", status_code=204)
async def delete_bulk_roll(bulk_id: uuid.UUID, who: Writer, db: Db) -> Response:
    try:
        await svc.delete_bulk_roll(db, who, bulk_id)
    except (svc.NotFoundError, svc.ConflictError) as exc:
        raise _http(exc) from exc
    return Response(status_code=204)
