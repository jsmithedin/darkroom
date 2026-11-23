import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import reset_db


@pytest.fixture(autouse=True)
async def clean_database(engine: AsyncEngine, migrated_db: str) -> None:
    """The load tests assume an empty database; other tests commit rows and leave them behind."""
    async with engine.begin() as conn:
        await reset_db(conn)
