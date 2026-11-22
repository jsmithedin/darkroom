import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.schemas.stock import (
    AdjustmentIn,
    FilmRef,
    FormatRef,
    MovementIn,
    MovementOut,
    MovementPage,
    MovementUpdate,
    StockRowOut,
)
from app.services import stock as svc

router = APIRouter(prefix="/api", tags=["stock"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


def _http(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, svc.NotFoundError) else 422
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/stock")
async def get_stock(_: Reader, db: Db, include_zero: bool = False) -> list[StockRowOut]:
    rows = await svc.get_stock(db, include_zero)
    return [
        StockRowOut(
            film=FilmRef(id=r.film_id, name=r.film_name, type=r.film_type),
            format=FormatRef(id=r.format_id, name=r.format_name),
            rolls=r.rolls,
        )
        for r in rows
    ]


@router.get("/stock-movements")
async def list_movements(
    _: Reader,
    db: Db,
    film: uuid.UUID | None = None,
    format: uuid.UUID | None = None,  # noqa: A002
    kind: Literal["purchase", "bulk_load", "given_away", "adjustment", "opening"] | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MovementPage:
    filters = svc.MovementFilters(film, format, kind, date_from, date_to)
    movements, total = await svc.list_movements(db, filters, svc.Page(limit, offset))
    return MovementPage(
        items=[MovementOut.model_validate(m) for m in movements],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/stock-movements", status_code=201)
async def create_movement(body: MovementIn, who: Writer, db: Db) -> MovementOut:
    try:
        return MovementOut.model_validate(await svc.create_movement(db, who, body))
    except (svc.InvalidMovementError, svc.NotFoundError) as exc:
        raise _http(exc) from exc


@router.post("/stock-adjustments", status_code=201)
async def create_adjustment(body: AdjustmentIn, who: Writer, db: Db) -> MovementOut:
    try:
        return MovementOut.model_validate(await svc.record_adjustment(db, who, body))
    except (svc.InvalidMovementError, svc.NotFoundError) as exc:
        raise _http(exc) from exc


@router.patch("/stock-movements/{movement_id}")
async def update_movement(
    movement_id: uuid.UUID, body: MovementUpdate, who: Writer, db: Db
) -> MovementOut:
    try:
        return MovementOut.model_validate(await svc.update_movement(db, who, movement_id, body))
    except (svc.InvalidMovementError, svc.NotFoundError) as exc:
        raise _http(exc) from exc


@router.delete("/stock-movements/{movement_id}", status_code=204)
async def delete_movement(movement_id: uuid.UUID, who: Writer, db: Db) -> Response:
    try:
        await svc.delete_movement(db, who, movement_id)
    except svc.NotFoundError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)
