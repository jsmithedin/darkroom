import re
from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.google import Identity
from app.auth.sessions import hash_token
from app.models import OAuthClient, OAuthCode
from tests.auth.conftest import CALLBACK, CHALLENGE, ISSUER
from tests.support import ORIGIN, FakeOIDC


async def register(
    client: AsyncClient, *, headers: dict[str, str] | None = None, **overrides: object
) -> Response:
    return await client.post(
        "/oauth/register",
        headers=headers,
        json={
            "client_name": "Film Assistant",
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
            **overrides,
        },
    )


def form_transaction(response: Response) -> str:
    assert response.status_code == 200, response.text
    match = re.search(r'name="transaction" value="([^"]+)"', response.text)
    assert match is not None
    return match[1]


async def test_register_returns_client_id(client: AsyncClient, engine: AsyncEngine) -> None:
    response = await register(client)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["client_id"]
    assert data["client_name"] == "Film Assistant"
    assert data["redirect_uris"] == [CALLBACK]
    assert data["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in data
    assert "no-store" in response.headers["cache-control"]
    async with AsyncSession(engine) as db:
        stored = await db.get(OAuthClient, data["client_id"])
        assert stored is not None
        assert stored.redirect_uris == [CALLBACK]


async def test_register_rejects_http_non_loopback_redirect(client: AsyncClient) -> None:
    response = await register(client, redirect_uris=["http://client.example/callback"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_browser_can_register_cross_origin(client: AsyncClient) -> None:
    origin = {"Origin": "https://client.example"}
    preflight = await client.options(
        "/oauth/register",
        headers=origin
        | {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, MCP-Protocol-Version",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["Access-Control-Allow-Origin"] == "*"
    assert preflight.headers["Access-Control-Allow-Methods"] == "POST"
    assert "content-type" in preflight.headers["Access-Control-Allow-Headers"].lower()
    success = await register(client, headers=origin)
    assert success.status_code == 201
    assert success.headers["Access-Control-Allow-Origin"] == "*"
    failure = await register(client, headers=origin, redirect_uris=["http://client.example"])
    assert failure.status_code == 400
    assert failure.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
async def test_register_accepts_http_loopback_redirect(client: AsyncClient, host: str) -> None:
    uri = f"http://{host}:36419/callback"
    response = await register(client, redirect_uris=[uri], application_type="native")
    assert response.status_code == 201
    assert response.json()["redirect_uris"] == [uri]


async def test_registration_is_rate_limited(client: AsyncClient, engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as db:
        db.add_all(
            OAuthClient(id=f"client-{index}", name="Client", redirect_uris=[CALLBACK])
            for index in range(20)
        )
        await db.commit()
    response = await register(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


async def test_authorize_requires_pkce_s256(
    client: AsyncClient, auth_params: dict[str, str]
) -> None:
    response = await client.get(
        "/oauth/authorize", params=auth_params | {"code_challenge_method": "plain"}
    )
    assert response.status_code == 302
    result = parse_qs(urlsplit(response.headers["location"]).query)
    assert result["error"] == ["invalid_request"]
    assert result["iss"] == [ISSUER]
    assert "code" not in result


async def test_authorize_unknown_redirect_uri_rejected_without_redirect(
    client: AsyncClient, auth_params: dict[str, str]
) -> None:
    response = await client.get(
        "/oauth/authorize", params=auth_params | {"redirect_uri": "https://client.example/other"}
    )
    assert response.status_code == 400
    assert "location" not in response.headers


async def test_unlisted_google_email_cannot_complete_authorize(
    client: AsyncClient, oidc: FakeOIDC, auth_params: dict[str, str], engine: AsyncEngine
) -> None:
    oidc.identity = Identity(
        sub="other", email="other@example.com", email_verified=True, name="Other"
    )
    login = await client.get("/oauth/authorize", params=auth_params)
    assert login.status_code == 302
    google_url = urlsplit(login.headers["location"])
    assert google_url.hostname == "accounts.example"
    state = parse_qs(google_url.query)["state"][0]
    response = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert response.status_code == 403
    assert "location" not in response.headers
    assert "darkroom_session" not in client.cookies
    async with AsyncSession(engine) as db:
        assert await db.scalar(select(func.count()).select_from(OAuthCode)) == 0

    retry = re.search(r"href='([^']+)'>Try again", response.text)
    assert retry is not None
    retry_url = urlsplit(unescape(retry[1]))
    assert retry_url.path == "/oauth/authorize"
    assert parse_qs(retry_url.query)["state"] == ["client-state"]


async def test_cancelled_google_sign_in_can_retry_authorization(
    client: AsyncClient, oidc: FakeOIDC, auth_params: dict[str, str]
) -> None:
    login = await client.get("/oauth/authorize", params=auth_params)
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    cancelled = await client.get(
        "/api/auth/callback", params={"error": "access_denied", "state": state}
    )
    assert cancelled.status_code == 400
    retry = re.search(r"href='([^']+)'>Try again", cancelled.text)
    assert retry is not None
    retry_login = await client.get(unescape(retry[1]))
    new_state = parse_qs(urlsplit(retry_login.headers["location"]).query)["state"][0]
    resume = await client.get("/api/auth/callback", params={"code": "c", "state": new_state})
    assert resume.status_code == 302
    assert urlsplit(resume.headers["location"]).path == "/oauth/authorize"
    form_transaction(await client.get(resume.headers["location"]))


async def test_consent_lists_requested_scopes(
    authed: AsyncClient, auth_params: dict[str, str]
) -> None:
    response = await authed.get("/oauth/authorize", params=auth_params)
    assert response.status_code == 200
    for text in ("Film Assistant", CALLBACK, "films:read", "films:write"):
        assert text in response.text
    assert "no-store" in response.headers["cache-control"]


async def test_response_includes_iss(
    client: AsyncClient, oidc: FakeOIDC, auth_params: dict[str, str], engine: AsyncEngine
) -> None:
    login = await client.get("/oauth/authorize", params=auth_params)
    assert login.status_code == 302
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    resume = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resume.status_code == 302
    assert urlsplit(resume.headers["location"]).path == "/oauth/authorize"
    page = await client.get(resume.headers["location"])
    transaction = form_transaction(page)
    response = await client.post(
        "/oauth/authorize/consent",
        data={"transaction": transaction, "decision": "approve"},
        headers=ORIGIN,
    )
    assert response.status_code == 303, response.text
    url = urlsplit(response.headers["location"])
    assert url.netloc == "client.example"
    assert url.path == "/callback"
    query = parse_qs(url.query)
    assert query["iss"] == [ISSUER]
    assert query["state"] == ["client-state"]
    assert query["mode"] == ["mcp"]
    code = query["code"][0]
    async with AsyncSession(engine) as db:
        stored = (await db.scalars(select(OAuthCode))).one()
        assert stored.code_hash == hash_token(code)
        assert stored.code_challenge == CHALLENGE
        assert stored.client_id == auth_params["client_id"]
        assert stored.redirect_uri == CALLBACK
        assert stored.resource == f"{ISSUER}/mcp"
        assert stored.scopes == ["films:read", "films:write"]
        assert stored.expires_at - stored.created_at == timedelta(seconds=60)
        assert stored.consumed_at is None

    replay = await client.post(
        "/oauth/authorize/consent",
        data={"transaction": transaction, "decision": "approve"},
        headers=ORIGIN,
    )
    assert replay.status_code == 400


async def test_consent_rejects_wrong_origin(
    authed: AsyncClient, auth_params: dict[str, str], engine: AsyncEngine
) -> None:
    page = await authed.get("/oauth/authorize", params=auth_params)
    response = await authed.post(
        "/oauth/authorize/consent",
        data={"transaction": form_transaction(page), "decision": "approve"},
        headers={"Origin": "https://other.example"},
    )
    assert response.status_code == 403
    async with AsyncSession(engine) as db:
        assert await db.scalar(select(func.count()).select_from(OAuthCode)) == 0


async def test_deny_returns_access_denied_without_code(
    authed: AsyncClient, auth_params: dict[str, str]
) -> None:
    page = await authed.get("/oauth/authorize", params=auth_params)
    response = await authed.post(
        "/oauth/authorize/consent",
        data={"transaction": form_transaction(page), "decision": "deny"},
    )
    assert response.status_code == 303
    result = parse_qs(urlsplit(response.headers["location"]).query)
    assert result["error"] == ["access_denied"]
    assert result["iss"] == [ISSUER]
    assert "code" not in result
