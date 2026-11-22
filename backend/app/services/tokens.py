import secrets
import uuid
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import hash_token
from app.models import PersonalAccessToken

TOKEN_PREFIX = "drk_"


async def create_pat(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    scopes: Collection[str],
    expires_at: datetime | None,
) -> tuple[PersonalAccessToken, str]:
    """Create a token. The plaintext is returned once and never stored."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    pat = PersonalAccessToken(
        user_id=user_id,
        name=name,
        prefix=raw[:8],
        token_hash=hash_token(raw),
        scopes=sorted(scopes),
        expires_at=expires_at,
    )
    db.add(pat)
    await db.commit()
    await db.refresh(pat)
    return pat, raw


async def list_pats(db: AsyncSession, user_id: uuid.UUID) -> list[PersonalAccessToken]:
    rows = await db.execute(
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id)
        .order_by(PersonalAccessToken.created_at.desc())
    )
    return list(rows.scalars())


async def revoke_pat(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> bool:
    """Revoke a token. Returns False if it does not exist or is not the user's."""
    pat = await db.get(PersonalAccessToken, token_id)
    if pat is None or pat.user_id != user_id:
        return False
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(UTC)
        await db.commit()
    return True
