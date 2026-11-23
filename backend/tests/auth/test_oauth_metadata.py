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
