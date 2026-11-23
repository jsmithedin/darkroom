from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def discovery_client() -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(public_base_url="https://darkroom.example"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://darkroom.example"
    ) as client:
        yield client


async def test_as_metadata_fields(discovery_client: AsyncClient) -> None:
    response = await discovery_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    assert response.json() == {
        "issuer": "https://darkroom.example",
        "authorization_endpoint": "https://darkroom.example/oauth/authorize",
        "token_endpoint": "https://darkroom.example/oauth/token",
        "registration_endpoint": "https://darkroom.example/oauth/register",
        "revocation_endpoint": "https://darkroom.example/oauth/revoke",
        "scopes_supported": ["films:read", "films:write"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
    }


async def test_issuer_comes_from_public_base_url_not_host_header(
    discovery_client: AsyncClient,
) -> None:
    response = await discovery_client.get(
        "/.well-known/oauth-authorization-server",
        headers={"Host": "other.example", "X-Forwarded-Host": "proxy.example"},
    )
    assert response.status_code == 200
    assert response.json()["issuer"] == "https://darkroom.example"


async def test_protected_resource_metadata_names_issuer(discovery_client: AsyncClient) -> None:
    response = await discovery_client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == "https://darkroom.example/mcp"
    assert response.json()["authorization_servers"] == ["https://darkroom.example"]
    assert response.json()["scopes_supported"] == ["films:read", "films:write"]


@pytest.mark.parametrize(
    ("public_base_url", "error"),
    [
        ("http://darkroom.example", "must be HTTPS"),
        ("https://darkroom.example?mode=dev", "must not have a query string"),
        ("https://darkroom.example#dev", "must not have a fragment"),
        ("https://darkroom.example?", "must not have an empty query string or fragment"),
        ("https://darkroom.example#", "must not have an empty query string or fragment"),
    ],
)
def test_invalid_issuer_is_rejected_at_startup(public_base_url: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        create_app(Settings(public_base_url=public_base_url))


async def test_local_development_issuer_allows_http() -> None:
    app = create_app(Settings(public_base_url="http://localhost:8000"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    assert response.json()["issuer"] == "http://localhost:8000"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
    ],
)
async def test_browser_can_read_discovery_metadata(
    discovery_client: AsyncClient, path: str
) -> None:
    origin = {"Origin": "https://client.example"}
    preflight = await discovery_client.options(
        path,
        headers=origin
        | {
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "MCP-Protocol-Version",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == "*"
    assert "mcp-protocol-version" in preflight.headers["Access-Control-Allow-Headers"].lower()

    response = await discovery_client.get(path, headers=origin)
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
