import asyncio

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from alembic import command
from app.models import User
from tests.helpers import alembic_config


async def run_alembic(fn, cfg: Config, *args: str) -> None:  # type: ignore[no-untyped-def]
    # env.py calls asyncio.run, so it must run off the test's event loop.
    await asyncio.to_thread(fn, cfg, *args)


async def table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("select tablename from pg_tables where schemaname = 'public'")
        )
        return {r[0] for r in rows}


@pytest.fixture
async def migrated(postgres_url: str) -> str:
    cfg = alembic_config(postgres_url)
    await run_alembic(command.upgrade, cfg, "head")
    return postgres_url


async def test_upgrade_head_then_downgrade_base(postgres_url: str, engine: AsyncEngine) -> None:
    cfg = alembic_config(postgres_url)
    await run_alembic(command.upgrade, cfg, "head")
    assert {"users", "oauth_clients", "oauth_codes", "oauth_tokens"} <= await table_names(engine)
    await run_alembic(command.downgrade, cfg, "base")
    assert await table_names(engine) <= {"alembic_version"}
    await run_alembic(command.upgrade, cfg, "head")  # leave migrated for other tests


async def test_user_email_case_insensitive_unique(migrated: str, db_session: AsyncSession) -> None:
    db_session.add(User(email="Me@Example.com", name="Me", google_sub="sub-1"))
    await db_session.flush()
    db_session.add(User(email="me@example.COM", name="Me again", google_sub="sub-2"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_models_match_migrations(migrated: str) -> None:
    """`alembic check` fails if the models drift from the migrations."""
    await run_alembic(command.check, alembic_config(migrated))
