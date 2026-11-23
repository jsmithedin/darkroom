from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl
from starlette.routing import Route

from app.auth.identity import ALL_SCOPES


def authorization_server_metadata(public_base_url: str) -> OAuthMetadata:
    issuer = public_base_url.rstrip("/")
    return OAuthMetadata.model_validate(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "scopes_supported": sorted(ALL_SCOPES),
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
        }
    )


def oauth_metadata_routes(public_base_url: str) -> list[Route]:
    metadata = authorization_server_metadata(public_base_url)
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            MetadataHandler(metadata).handle,
            methods=["GET"],
        ),
        *create_protected_resource_routes(
            resource_url=AnyHttpUrl(f"{metadata.issuer}/mcp"),
            authorization_servers=[metadata.issuer],
            scopes_supported=metadata.scopes_supported,
        ),
    ]
