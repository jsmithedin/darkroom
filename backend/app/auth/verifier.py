from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from mcp.server.auth.provider import AccessToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.identity import READ, WRITE, Principal
from app.auth.sessions import hash_token
from app.models import OAuthToken, PersonalAccessToken, User
from app.services.tokens import TOKEN_PREFIX

OAUTH_ACCESS_PREFIX = "dro_"
EngineGetter = Callable[[], AsyncEngine]


async def verify_bearer(
    db: AsyncSession, raw: str, audience: str | None = None
) -> Principal | None:
    """Resolve a bearer token to a Principal, or None if it is unknown, revoked or expired.

    Personal access tokens work anywhere. OAuth access tokens are bound to the MCP endpoint
    (RFC 8707), so they are only accepted when `audience` is that endpoint's URL.
    """
    if raw.startswith(TOKEN_PREFIX):
        return await _verify_pat(db, raw)
    if raw.startswith(OAUTH_ACCESS_PREFIX) and audience is not None:
        return await _verify_oauth(db, raw, audience)
    return None


async def _verify_pat(db: AsyncSession, raw: str) -> Principal | None:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(PersonalAccessToken, User)
            .join(User, User.id == PersonalAccessToken.user_id)
            .where(PersonalAccessToken.token_hash == hash_token(raw))
        )
    ).one_or_none()
    if row is None:
        return None
    pat, user = row
    if pat.revoked_at is not None or not user.is_active:
        return None
    if pat.expires_at is not None and pat.expires_at <= now:
        return None
    pat.last_used_at = now
    await db.commit()
    return Principal(
        user_id=pat.user_id,
        scopes=frozenset(pat.scopes),
        via="pat",
        token_id=pat.id,
    )


async def _verify_oauth(db: AsyncSession, raw: str, audience: str) -> Principal | None:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(OAuthToken, User)
            .join(User, User.id == OAuthToken.user_id)
            .where(OAuthToken.access_token_hash == hash_token(raw))
        )
    ).one_or_none()
    if row is None:
        return None
    token, user = row
    if token.revoked_at is not None or not user.is_active or token.access_expires_at <= now:
        return None
    if token.resource.rstrip("/") != audience.rstrip("/"):
        return None
    return Principal(
        user_id=token.user_id,
        scopes=frozenset(token.scopes),
        via="oauth",
        token_id=token.id,
        client_id=token.client_id,
    )


class DarkroomTokenVerifier:
    """SDK `TokenVerifier` for /mcp: accepts personal access tokens and OAuth access tokens."""

    def __init__(self, engine: EngineGetter, resource: str) -> None:
        self._engine = engine
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        maker = async_sessionmaker(self._engine(), expire_on_commit=False)
        async with maker() as db:
            principal = await verify_bearer(db, token, audience=self._resource)
        if principal is None:
            return None
        scopes = set(principal.scopes)
        if WRITE in scopes:
            scopes.add(READ)  # write implies read; the SDK compares scopes literally
        return AccessToken(
            token=token,
            client_id=principal.client_id or principal.via,
            scopes=sorted(scopes),
            resource=self._resource,
            subject=str(principal.user_id),
            claims={
                "user_id": str(principal.user_id),
                "via": principal.via,
                "token_id": str(principal.token_id) if principal.token_id else None,
                "client_id": principal.client_id,
                "scopes": sorted(principal.scopes),
            },
        )


def principal_from_access_token(access: AccessToken) -> Principal:
    """Rebuild the Principal that DarkroomTokenVerifier authenticated (used by MCP tools)."""
    claims = access.claims or {}
    return Principal(
        user_id=UUID(claims["user_id"]),
        scopes=frozenset(claims["scopes"]),
        via=claims["via"],
        token_id=UUID(claims["token_id"]) if claims.get("token_id") else None,
        client_id=claims.get("client_id"),
    )
