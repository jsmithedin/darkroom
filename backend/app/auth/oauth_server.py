import base64
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import (
    cors_middleware,
    create_protected_resource_routes,
    validate_issuer_url,
)
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from app.auth.identity import ALL_SCOPES, READ
from app.auth.sessions import hash_token
from app.models import OAuthClient, OAuthCode, OAuthToken

AUTHORIZE_PATH = "/oauth/authorize"
REGISTRATION_LIMIT = 20
REGISTRATION_WINDOW = timedelta(minutes=1)
CODE_LIFETIME = timedelta(seconds=60)
ACCESS_LIFETIME = timedelta(seconds=3600)
REFRESH_LIFETIME = timedelta(days=30)
ACCESS_PREFIX = "dro_"
REFRESH_PREFIX = "drr_"
CODE_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
GRANT_TYPES = ("authorization_code", "refresh_token")
RESPONSE_TYPES = ("code",)
PKCE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")
RESPONSE_PARAMETERS = {"code", "error", "error_description", "error_uri", "state", "iss"}


class RegistrationRequest(BaseModel):
    client_name: str = Field(default="Unnamed client", min_length=1, max_length=100)
    redirect_uris: list[Annotated[str, Field(max_length=2048)]] = Field(min_length=1, max_length=10)
    token_endpoint_auth_method: Literal["none"] = "none"
    grant_types: tuple[Literal["authorization_code", "refresh_token"], ...] = Field(
        default=("authorization_code",), min_length=1, max_length=2
    )
    response_types: tuple[Literal["code"], ...] = Field(
        default=("code",), min_length=1, max_length=1
    )
    software_statement: str | None = None


class AuthorizationRequest(BaseModel):
    client_id: str
    redirect_uri: str
    response_type: str = ""
    code_challenge: str = ""
    code_challenge_method: str = ""
    resource: str = ""
    scope: str = READ
    state: str | None = None

    @property
    def scopes(self) -> list[str]:
        return sorted(set(self.scope.split()))

    def error(self, issuer: str) -> tuple[str, str] | None:
        if self.response_type != "code":
            return "unsupported_response_type", "Darkroom supports the code response type."
        if self.code_challenge_method != "S256" or not PKCE_CHALLENGE.fullmatch(
            self.code_challenge
        ):
            return "invalid_request", "A valid S256 PKCE challenge is required."
        if self.resource != f"{issuer}/mcp":
            return "invalid_target", "The resource must identify Darkroom's MCP endpoint."
        if not self.scopes or not ALL_SCOPES.issuperset(self.scopes):
            return "invalid_scope", "Darkroom supports films:read and films:write."
        return None


def valid_redirect_uri(uri: str) -> bool:
    if (
        not uri
        or "\\" in uri
        or "#" in uri
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in uri)
    ):
        return False
    try:
        parsed = urlsplit(uri)
        # Reading port also rejects malformed or out-of-range values.
        if parsed.port == 0:
            return False
    except ValueError:
        return False
    if not parsed.hostname or parsed.username is not None:
        return False
    if RESPONSE_PARAMETERS.intersection(
        key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        return False
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


async def register_client(db: AsyncSession, request: RegistrationRequest) -> OAuthClient | None:
    async with db.begin():
        # Count and insert under the same lock so app workers share the registration budget.
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtext("darkroom:oauth:register")))
        )
        cutoff = datetime.now(UTC) - REGISTRATION_WINDOW
        count = await db.scalar(
            select(func.count()).select_from(OAuthClient).where(OAuthClient.created_at > cutoff)
        )
        if count is not None and count >= REGISTRATION_LIMIT:
            return None
        client = OAuthClient(
            id=secrets.token_urlsafe(24),
            name=request.client_name.strip() or "Unnamed client",
            redirect_uris=request.redirect_uris,
        )
        db.add(client)
        await db.flush()
    return client


async def issue_authorization_code(
    db: AsyncSession, request: AuthorizationRequest, user_id: UUID, transaction_id: UUID
) -> str | None:
    code = secrets.token_urlsafe(32)
    created = datetime.now(UTC)
    issued = await db.scalar(
        insert(OAuthCode)
        .values(
            id=transaction_id,
            user_id=user_id,
            client_id=request.client_id,
            code_hash=hash_token(code),
            code_challenge=request.code_challenge,
            redirect_uri=request.redirect_uri,
            resource=request.resource,
            scopes=request.scopes,
            created_at=created,
            expires_at=created + CODE_LIFETIME,
        )
        .on_conflict_do_nothing(index_elements=[OAuthCode.id])
        .returning(OAuthCode.id)
    )
    await db.commit()
    return code if issued is not None else None


def authorization_server_metadata(public_base_url: str) -> OAuthMetadata:
    issuer = public_base_url.rstrip("/")
    issuer_url = AnyHttpUrl(issuer)
    validate_issuer_url(issuer_url)
    # The SDK checks non-empty values. Bare "?" and "#" are invalid here too.
    if issuer_url.query == "" or issuer_url.fragment == "":
        raise ValueError("Issuer URL must not have an empty query string or fragment")
    return OAuthMetadata.model_validate(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}{AUTHORIZE_PATH}",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "scopes_supported": sorted(ALL_SCOPES),
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
            "response_types_supported": RESPONSE_TYPES,
            "grant_types_supported": GRANT_TYPES,
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
        }
    )


def oauth_metadata_routes(public_base_url: str) -> list[Route]:
    metadata = authorization_server_metadata(public_base_url)
    discovery_methods = ["GET", "OPTIONS"]
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            cors_middleware(MetadataHandler(metadata).handle, discovery_methods),
            methods=discovery_methods,
        ),
        *create_protected_resource_routes(
            resource_url=AnyHttpUrl(f"{metadata.issuer}/mcp"),
            authorization_servers=[metadata.issuer],
            scopes_supported=metadata.scopes_supported,
        ),
    ]


class OAuthFailure(Exception):
    """An RFC 6749 error response for the token or revocation endpoint."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status


class IssuedTokens(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    refresh_token: str
    scope: str


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _new_token_row(
    *, client_id: str, user_id: UUID, family_id: UUID, resource: str, scopes: list[str]
) -> tuple[OAuthToken, IssuedTokens]:
    access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = OAuthToken(
        client_id=client_id,
        user_id=user_id,
        family_id=family_id,
        access_token_hash=hash_token(access),
        refresh_token_hash=hash_token(refresh),
        resource=resource,
        scopes=scopes,
        created_at=now,
        access_expires_at=now + ACCESS_LIFETIME,
        refresh_expires_at=now + REFRESH_LIFETIME,
    )
    issued = IssuedTokens(
        access_token=access,
        expires_in=int(ACCESS_LIFETIME.total_seconds()),
        refresh_token=refresh,
        scope=" ".join(scopes),
    )
    return row, issued


async def exchange_authorization_code(
    db: AsyncSession,
    *,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    resource: str | None,
) -> IssuedTokens:
    """Trade a single-use code for tokens after checking PKCE, client, redirect URI, resource."""
    grant_error = OAuthFailure("invalid_grant", "The authorization code is invalid or expired.")
    stored = await db.scalar(
        select(OAuthCode).where(OAuthCode.code_hash == hash_token(code)).with_for_update()
    )
    if stored is None or stored.client_id != client_id:
        raise grant_error
    now = datetime.now(UTC)
    # Whatever happens next, the code is spent: a wrong guess cannot be retried.
    already_used = stored.consumed_at is not None
    if not already_used:
        stored.consumed_at = now
    await db.commit()
    if already_used or stored.expires_at <= now:
        raise grant_error
    if redirect_uri != stored.redirect_uri:
        raise OAuthFailure("invalid_grant", "The redirect URI does not match the request.")
    if resource is not None and resource != stored.resource:
        raise OAuthFailure("invalid_target", "The resource does not match the request.")
    if not CODE_VERIFIER.fullmatch(code_verifier) or not secrets.compare_digest(
        pkce_challenge(code_verifier), stored.code_challenge
    ):
        raise OAuthFailure("invalid_grant", "The code verifier does not match the challenge.")
    row, issued = _new_token_row(
        client_id=client_id,
        user_id=stored.user_id,
        family_id=uuid4(),
        resource=stored.resource,
        scopes=list(stored.scopes),
    )
    db.add(row)
    await db.commit()
    return issued


async def revoke_family(db: AsyncSession, family_id: UUID) -> None:
    await db.execute(
        update(OAuthToken)
        .where(OAuthToken.family_id == family_id, OAuthToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def refresh_tokens(
    db: AsyncSession, *, client_id: str, refresh_token: str, scope: str | None
) -> IssuedTokens:
    """Rotate a refresh token. Presenting one that was already rotated revokes its family."""
    invalid = OAuthFailure("invalid_grant", "The refresh token is invalid or expired.")
    stored = await db.scalar(
        select(OAuthToken)
        .where(OAuthToken.refresh_token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    if stored is None or stored.client_id != client_id:
        raise invalid
    now = datetime.now(UTC)
    if stored.rotated_at is not None or stored.revoked_at is not None:
        # A rotated or revoked token coming back means it may have been copied.
        await revoke_family(db, stored.family_id)
        await db.commit()
        raise invalid
    if stored.refresh_expires_at <= now:
        raise invalid
    requested = sorted(set(scope.split())) if scope else list(stored.scopes)
    if not requested or not set(requested).issubset(stored.scopes):
        raise OAuthFailure("invalid_scope", "Scopes cannot be widened when refreshing.")
    stored.rotated_at = now
    row, issued = _new_token_row(
        client_id=client_id,
        user_id=stored.user_id,
        family_id=stored.family_id,
        resource=stored.resource,
        scopes=requested,
    )
    db.add(row)
    await db.commit()
    return issued


async def revoke_token(db: AsyncSession, *, client_id: str, token: str) -> None:
    """Revoke the family holding this access or refresh token. Unknown tokens are ignored."""
    digest = hash_token(token)
    stored = await db.scalar(
        select(OAuthToken).where(
            or_(OAuthToken.access_token_hash == digest, OAuthToken.refresh_token_hash == digest)
        )
    )
    if stored is None or stored.client_id != client_id:
        return
    await revoke_family(db, stored.family_id)
    await db.commit()
