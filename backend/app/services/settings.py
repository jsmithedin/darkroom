from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import Principal
from app.models import AppSettings


class InvalidSettingError(Exception):
    """A settings value is not acceptable."""


async def get_settings(db: AsyncSession) -> AppSettings:
    """The single settings row (created by migration 0004)."""
    row = (await db.execute(select(AppSettings))).scalar_one_or_none()
    if row is None:
        raise RuntimeError("settings row is missing; run migrations")
    return row


async def update_settings(
    db: AsyncSession, actor: Principal, values: dict[str, Any]
) -> AppSettings:
    row = await get_settings(db)
    if "timezone" in values:
        try:
            ZoneInfo(values["timezone"])
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise InvalidSettingError(f"Unknown timezone '{values['timezone']}'.") from exc
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = actor.user_id
    await db.commit()
    await db.refresh(row)
    return row
