from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.sessions import ABSOLUTE, SLIDING
from app.models import User, UserSession
from tests.support import sign_in


async def backdate(engine: AsyncEngine, **values: datetime) -> None:
    async with AsyncSession(engine) as s:
        await s.execute(update(UserSession).values(**values))
        await s.commit()


async def test_expired_session_rejected(client: AsyncClient, engine: AsyncEngine, oidc) -> None:  # type: ignore[no-untyped-def]
    await sign_in(client)
    await backdate(engine, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert (await client.get("/api/me")).status_code == 401


async def test_sliding_expiry_extends_but_is_capped(
    client: AsyncClient,
    engine: AsyncEngine,
    oidc,  # type: ignore[no-untyped-def]
) -> None:
    await sign_in(client)
    now = datetime.now(UTC)
    # 80 days old, last seen long enough ago to be touched
    await backdate(
        engine,
        created_at=now - timedelta(days=80),
        last_seen_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=1),
    )
    assert (await client.get("/api/me")).status_code == 200
    async with AsyncSession(engine) as s:
        sess = (await s.execute(UserSession.__table__.select())).one()
    assert sess.expires_at > now + timedelta(days=9)
    assert sess.expires_at <= sess.created_at + ABSOLUTE
    assert sess.expires_at < now + SLIDING


async def test_absolute_cap_rejects_old_session(
    client: AsyncClient,
    engine: AsyncEngine,
    oidc,  # type: ignore[no-untyped-def]
) -> None:
    await sign_in(client)
    now = datetime.now(UTC)
    await backdate(
        engine, created_at=now - ABSOLUTE - timedelta(days=1), expires_at=now + timedelta(days=5)
    )
    assert (await client.get("/api/me")).status_code == 401


async def test_deactivated_user_rejected(
    client: AsyncClient,
    engine: AsyncEngine,
    oidc,  # type: ignore[no-untyped-def]
) -> None:
    await sign_in(client)
    async with AsyncSession(engine) as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    assert (await client.get("/api/me")).status_code == 401
