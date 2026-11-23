import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.schemas.devtimes import DevTimeGroup, DevTimeRefIn, DevTimeRefOut, DevTimeRefUpdate
from app.services import devtimes as svc

router = APIRouter(prefix="/api", tags=["dev-times"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/dev-times")
async def dev_times(
    _: Reader,
    db: Db,
    film: uuid.UUID | None = None,
    ei: Decimal | None = None,
    developer: uuid.UUID | None = None,
) -> list[DevTimeGroup]:
    return await svc.grouped_dev_times(db, film, ei, developer)


@router.get("/dev-time-refs")
async def list_refs(_: Reader, db: Db) -> list[DevTimeRefOut]:
    return await svc.list_refs(db)


@router.post("/dev-time-refs", status_code=201)
async def create_ref(body: DevTimeRefIn, who: Writer, db: Db) -> DevTimeRefOut:
    try:
        return await svc.create_ref(db, who, body)
    except (svc.InvalidRefError, svc.ConflictError) as exc:
        raise _http(exc) from exc


@router.patch("/dev-time-refs/{ref_id}")
async def update_ref(
    ref_id: uuid.UUID, body: DevTimeRefUpdate, who: Writer, db: Db
) -> DevTimeRefOut:
    try:
        return await svc.update_ref(db, who, ref_id, body)
    except (svc.NotFoundError, svc.InvalidRefError, svc.ConflictError) as exc:
        raise _http(exc) from exc


@router.delete("/dev-time-refs/{ref_id}", status_code=204)
async def delete_ref(ref_id: uuid.UUID, _: Writer, db: Db) -> Response:
    try:
        await svc.delete_ref(db, ref_id)
    except svc.NotFoundError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)
