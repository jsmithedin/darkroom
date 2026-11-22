import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserSession

SESSION_COOKIE = "darkroom_session"
SLIDING = timedelta(days=30)
ABSOLUTE = timedelta(days=90)
TOUCH_AFTER = timedelta(minutes=10)  # avoid a write on every request


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_session(db: AsyncSession, user: User) -> str:
    """Create a session and return the raw cookie value (never stored)."""
    raw = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw),
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen_at=now,
            expires_at=now + SLIDING,
        )
    )
    await db.commit()
    return raw


async def lookup_session(db: AsyncSession, raw: str) -> tuple[UserSession, User] | None:
    """Return a live session and its active user, sliding the expiry (capped at 90 days)."""
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(raw))
        )
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    if session.expires_at <= now or session.created_at + ABSOLUTE <= now or not user.is_active:
        return None
    if now - session.last_seen_at > TOUCH_AFTER:
        session.last_seen_at = now
        session.expires_at = min(now + SLIDING, session.created_at + ABSOLUTE)
        await db.commit()
    return session, user


async def delete_session(db: AsyncSession, raw: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(raw)))
    await db.commit()
