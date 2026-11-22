from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.config import Settings
from app.main import create_app
from tests.helpers import alembic_config
from tests.support import authed, bearer_client, gear, oidc, scoped

__all__ = ["authed", "bearer_client", "gear", "oidc", "scoped"]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Async SQLAlchemy URL for a throwaway Postgres 16 container."""
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def test_settings(postgres_url: str) -> Settings:
    return Settings(
        database_url=postgres_url,
        public_base_url="https://film.jamielab.uk",
        allowed_emails=["me@example.com"],
        session_secret="test-secret",
    )


@pytest.fixture(scope="session")
def migrated_db(postgres_url: str) -> str:
    """Schema at head, once per session. Tests that downgrade must upgrade again."""
    command.upgrade(alembic_config(postgres_url), "head")
    return postgres_url


KEEP_TABLES = {"alembic_version", "users", "formats", "settings"}
SEED_FORMATS = ("35mm", "120", "110")


async def reset_db(conn: AsyncConnection) -> None:
    """Return the database to its freshly migrated state (seed rows kept, everything else gone)."""
    rows = await conn.execute(text("select tablename from pg_tables where schemaname = 'public'"))
    tables = [r[0] for r in rows if r[0] not in KEEP_TABLES]
    if tables:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    await conn.execute(text("DELETE FROM users"))  # sessions and tokens cascade
    await conn.execute(text("DELETE FROM formats WHERE name NOT IN ('35mm', '120', '110')"))
    await conn.execute(
        text("UPDATE settings SET leader_mm = 250, frame_pitch_mm = 38, timezone = 'Europe/London'")
    )


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(postgres_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine, migrated_db: str) -> AsyncIterator[AsyncSession]:
    """Session whose work is rolled back at the end of the test."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        maker = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with maker() as session:
            yield session
        if trans.is_active:
            await trans.rollback()


@pytest.fixture
async def client(
    test_settings: Settings, engine: AsyncEngine, migrated_db: str
) -> AsyncIterator[AsyncClient]:
    async with engine.begin() as conn:
        await reset_db(conn)
    app = create_app(test_settings)
    app.state.engine = engine
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://film.jamielab.uk"
    ) as c:
        yield c
