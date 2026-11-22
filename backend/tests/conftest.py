from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.config import Settings
from app.main import create_app


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


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(postgres_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session whose work is rolled back at the end of the test."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        maker = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with maker() as session:
            yield session
        await trans.rollback()


@pytest.fixture
async def client(test_settings: Settings, engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    app.state.engine = engine
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://film.jamielab.uk"
    ) as c:
        yield c
