import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import READ, WRITE, Principal, require_scope
from app.db import get_session
from app.models.reference import RefKind
from app.schemas import reference as s
from app.services import reference as svc

router = APIRouter(prefix="/api")

Reader = Annotated[Principal, Depends(require_scope(READ))]
Writer = Annotated[Principal, Depends(require_scope(WRITE))]
Db = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Spec:
    kind: RefKind
    create: type[BaseModel]
    update: type[BaseModel]
    out: type[s.ItemOut]


SPECS = [
    Spec(RefKind.CAMERAS, s.CameraCreate, s.CameraUpdate, s.CameraOut),
    Spec(RefKind.LENSES, s.NamedCreate, s.NamedUpdate, s.ItemOut),
    Spec(RefKind.DEVELOPERS, s.NamedCreate, s.NamedUpdate, s.ItemOut),
    Spec(RefKind.FILTERS, s.NamedCreate, s.NamedUpdate, s.ItemOut),
    Spec(RefKind.FILMS, s.FilmCreate, s.FilmUpdate, s.FilmOut),
    Spec(RefKind.FORMATS, s.NamedCreate, s.NamedUpdate, s.ItemOut),
]


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


def add_routes(spec: Spec) -> None:
    """Register list/create/update/archive/unarchive for one reference kind."""
    kind, out = spec.kind, spec.out
    create_model, update_model = spec.create, spec.update
    path = f"/{kind.value}"
    tags: list[str | Enum] = [kind.value]

    @router.get(path, response_model=list[out], tags=tags, name=f"list_{kind.value}")  # type: ignore[valid-type]
    async def list_(_: Reader, db: Db, include_archived: bool = False) -> list[object]:
        return list(await svc.list_items(db, kind, include_archived))

    @router.post(path, response_model=out, status_code=201, tags=tags, name=f"create_{kind.value}")
    async def create(body: create_model, who: Writer, db: Db) -> object:  # type: ignore[valid-type]
        data = body.model_dump()  # type: ignore[attr-defined]
        try:
            return await svc.create_item(db, kind, data, who.user_id)
        except svc.DuplicateNameError as exc:
            raise _translate(exc) from exc

    @router.patch(path + "/{item_id}", response_model=out, tags=tags, name=f"update_{kind.value}")
    async def update(
        item_id: uuid.UUID,
        body: update_model,  # type: ignore[valid-type]
        who: Writer,
        db: Db,
    ) -> object:
        data = body.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
        try:
            return await svc.update_item(db, kind, item_id, data, who.user_id)
        except (svc.NotFoundError, svc.DuplicateNameError) as exc:
            raise _translate(exc) from exc

    @router.post(
        path + "/{item_id}/archive", response_model=out, tags=tags, name=f"archive_{kind.value}"
    )
    async def archive(item_id: uuid.UUID, who: Writer, db: Db) -> object:
        try:
            return await svc.archive_item(db, kind, item_id, who.user_id)
        except svc.NotFoundError as exc:
            raise _translate(exc) from exc

    @router.post(
        path + "/{item_id}/unarchive",
        response_model=out,
        tags=tags,
        name=f"unarchive_{kind.value}",
    )
    async def unarchive(item_id: uuid.UUID, who: Writer, db: Db) -> object:
        try:
            return await svc.unarchive_item(db, kind, item_id, who.user_id)
        except svc.NotFoundError as exc:
            raise _translate(exc) from exc


for _spec in SPECS:
    add_routes(_spec)
