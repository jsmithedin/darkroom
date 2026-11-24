import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import AuditEvent, OAuthClient, PersonalAccessToken


async def record_audit(
    session: AsyncSession,
    principal: Principal,
    tool: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: dict[str, Any],
) -> None:
    """Record a successful tool write. Call it only after the write itself has committed."""
    session.add(
        AuditEvent(
            user_id=principal.user_id,
            via=principal.via,
            token_id=principal.token_id,
            client_id=principal.client_id,
            tool=tool,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
        )
    )
    await session.commit()


class AuditEventRow(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    tool: str
    entity_type: str
    entity_id: uuid.UUID | None
    summary: dict[str, Any]
    via: str
    token_id: uuid.UUID | None
    client_id: str | None
    actor: str | None  # the token's name or the OAuth client's name, if it still exists


async def list_audit(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[AuditEventRow], int]:
    total = await session.scalar(select(func.count()).select_from(AuditEvent)) or 0
    rows = await session.execute(
        select(AuditEvent, PersonalAccessToken.name, OAuthClient.name)
        .outerjoin(
            PersonalAccessToken,
            (AuditEvent.via == "pat") & (PersonalAccessToken.id == AuditEvent.token_id),
        )
        .outerjoin(OAuthClient, OAuthClient.id == AuditEvent.client_id)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
        .limit(limit)
        .offset(offset)
    )
    out = [
        AuditEventRow(
            id=e.id,
            occurred_at=e.occurred_at,
            tool=e.tool,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            summary=e.summary,
            via=e.via,
            token_id=e.token_id,
            client_id=e.client_id,
            actor=pat_name or client_name,
        )
        for e, pat_name, client_name in rows
    ]
    return out, total
