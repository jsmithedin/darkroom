from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, Principal, require_scope
from app.db import get_session
from app.services import audit as svc

router = APIRouter(prefix="/api", tags=["audit"])

Reader = Annotated[Principal, Depends(require_scope(READ))]
Db = Annotated[AsyncSession, Depends(get_session)]


class AuditPage(BaseModel):
    items: list[svc.AuditEventRow]
    total: int
    limit: int
    offset: int


@router.get("/audit-events")
async def list_audit_events(
    _: Reader,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    """Writes made through MCP tools, newest first. Read-only."""
    items, total = await svc.list_audit(db, limit, offset)
    return AuditPage(items=items, total=total, limit=limit, offset=offset)
