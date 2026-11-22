import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import MODELS, NamedItem, RefKind


class NotFoundError(Exception):
    """No such reference item."""


class DuplicateNameError(Exception):
    """Another item of this kind already has the name."""


_SINGULAR = {
    RefKind.CAMERAS: "camera",
    RefKind.LENSES: "lens",
    RefKind.DEVELOPERS: "developer",
    RefKind.FILTERS: "filter",
    RefKind.FILMS: "film",
    RefKind.FORMATS: "format",
}


def _duplicate(kind: RefKind, name: str, archived: bool) -> DuplicateNameError:
    note = " It is archived; unarchive it instead." if archived else ""
    return DuplicateNameError(f"A {_SINGULAR[kind]} named '{name}' already exists.{note}")


async def list_items(
    db: AsyncSession, kind: RefKind, include_archived: bool = False
) -> list[NamedItem]:
    model = MODELS[kind]
    stmt = select(model).order_by(model.name)
    if not include_archived:
        stmt = stmt.where(model.archived_at.is_(None))
    return list((await db.execute(stmt)).scalars())


async def get_item(db: AsyncSession, kind: RefKind, item_id: uuid.UUID) -> NamedItem:
    item = await db.get(MODELS[kind], item_id)
    if item is None:
        raise NotFoundError(f"No such {_SINGULAR[kind]}.")
    return item


async def _check_name_free(
    db: AsyncSession, kind: RefKind, name: str, exclude: uuid.UUID | None = None
) -> None:
    model = MODELS[kind]
    stmt = select(model).where(model.name == name)
    if exclude is not None:
        stmt = stmt.where(model.id != exclude)
    existing = (await db.execute(stmt)).scalars().first()
    if existing is not None:
        raise _duplicate(kind, name, existing.archived_at is not None)


async def _commit(db: AsyncSession, kind: RefKind, name: str) -> None:
    """Commit; a lost race on the unique name still comes back as a duplicate error."""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _duplicate(kind, name, False) from exc


async def create_item(
    db: AsyncSession, kind: RefKind, data: dict[str, Any], actor: uuid.UUID
) -> NamedItem:
    await _check_name_free(db, kind, data["name"])
    item = MODELS[kind](**data, created_by=actor, updated_by=actor)
    db.add(item)
    await _commit(db, kind, data["name"])
    await db.refresh(item)
    return item


async def update_item(
    db: AsyncSession,
    kind: RefKind,
    item_id: uuid.UUID,
    data: dict[str, Any],
    actor: uuid.UUID,
) -> NamedItem:
    """Apply only the fields present in `data` (a PATCH)."""
    item = await get_item(db, kind, item_id)
    if data.get("name") is not None:
        await _check_name_free(db, kind, data["name"], exclude=item.id)
    for key, value in data.items():
        if value is None and key in {"name", "type", "box_iso", "fixed_lens"}:
            continue  # these columns are not nullable; null means "unchanged"
        setattr(item, key, value)
    item.updated_by = actor
    await _commit(db, kind, data.get("name") or item.name)
    await db.refresh(item)
    return item


async def archive_item(
    db: AsyncSession, kind: RefKind, item_id: uuid.UUID, actor: uuid.UUID
) -> NamedItem:
    item = await get_item(db, kind, item_id)
    if item.archived_at is None:
        item.archived_at = datetime.now(UTC)
        item.updated_by = actor
        await db.commit()
        await db.refresh(item)
    return item


async def unarchive_item(
    db: AsyncSession, kind: RefKind, item_id: uuid.UUID, actor: uuid.UUID
) -> NamedItem:
    item = await get_item(db, kind, item_id)
    if item.archived_at is not None:
        item.archived_at = None
        item.updated_by = actor
        await db.commit()
        await db.refresh(item)
    return item
