import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal, require_session_principal
from app.db import get_session
from app.models import PersonalAccessToken
from app.services import tokens

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

Scope = Literal["films:read", "films:write"]


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: set[Scope] = Field(min_length=1)
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def in_future(cls, v: datetime | None) -> datetime | None:
        if v is not None and v <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return v


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class TokenCreated(TokenOut):
    token: str = Field(description="The token. Shown once; it cannot be retrieved later.")


def _out(pat: PersonalAccessToken) -> TokenOut:
    return TokenOut.model_validate(pat)


@router.get("")
async def list_tokens(
    principal: Annotated[Principal, Depends(require_session_principal)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[TokenOut]:
    return [_out(p) for p in await tokens.list_pats(db, principal.user_id)]


@router.post("", status_code=201)
async def create_token(
    body: TokenCreate,
    principal: Annotated[Principal, Depends(require_session_principal)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> TokenCreated:
    pat, raw = await tokens.create_pat(
        db, principal.user_id, body.name, body.scopes, body.expires_at
    )
    return TokenCreated(**_out(pat).model_dump(), token=raw)


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_session_principal)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if not await tokens.revoke_pat(db, principal.user_id, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return Response(status_code=204)
