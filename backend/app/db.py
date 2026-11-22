from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the app's engine; commit is the caller's job."""
    maker = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with maker() as session:
        yield session
