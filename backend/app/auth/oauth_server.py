import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import (
    cors_middleware,
    create_protected_resource_routes,
    validate_issuer_url,
)
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from app.auth.identity import ALL_SCOPES, READ
from app.auth.sessions import hash_token
from app.models import OAuthClient, OAuthCode

AUTHORIZE_PATH = "/oauth/authorize"
REGISTRATION_LIMIT = 20
REGISTRATION_WINDOW = timedelta(minutes=1)
CODE_LIFETIME = timedelta(seconds=60)
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
