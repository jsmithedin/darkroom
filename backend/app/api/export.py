from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, Principal, require_scope
from app.db import get_session
from app.services import export as svc

router = APIRouter(prefix="/api/export", tags=["export"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Db = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def list_tables(_: Reader) -> list[str]:
    return list(svc.EXPORT_TABLES)


@router.get(
    "/{table}.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def export_csv(table: str, _: Reader, db: Db) -> Response:
    """One table as CSV. The data is small (one person's film log), so it is read in full before
    the response starts, which keeps the database session's lifetime simple."""
    try:
        chunks = [chunk async for chunk in svc.export_table(db, table)]
    except svc.UnknownTableError as exc:
        raise HTTPException(status_code=404, detail="No such table.") from exc
    return Response(
        content="".join(chunks),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="darkroom-{table}.csv"',
            # Private data behind a login: a CDN (Cloudflare caches .csv by default) must never
            # keep a copy and serve it without asking the app.
            "Cache-Control": "private, no-store",
        },
    )
