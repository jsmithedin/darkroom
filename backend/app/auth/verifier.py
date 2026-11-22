from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.auth.sessions import hash_token
from app.models import PersonalAccessToken, User
from app.services.tokens import TOKEN_PREFIX


async def verify_bearer(db: AsyncSession, raw: str) -> Principal | None:
    """Resolve a bearer token to a Principal, or None if it is unknown, revoked or expired.

    Personal access tokens only for now; OAuth access tokens join this in Phase 6.
    """
    if not raw.startswith(TOKEN_PREFIX):
        return None
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(PersonalAccessToken, User)
            .join(User, User.id == PersonalAccessToken.user_id)
            .where(PersonalAccessToken.token_hash == hash_token(raw))
        )
    ).one_or_none()
    if row is None:
        return None
    pat, user = row
    if pat.revoked_at is not None or not user.is_active:
        return None
    if pat.expires_at is not None and pat.expires_at <= now:
        return None
    pat.last_used_at = now
    await db.commit()
    return Principal(
        user_id=pat.user_id,
        scopes=frozenset(pat.scopes),
        via="pat",
        token_id=pat.id,
    )
