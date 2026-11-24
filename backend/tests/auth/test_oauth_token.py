import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import OAuthClient, OAuthCode, OAuthToken
from tests.auth.conftest import CALLBACK, ISSUER
from tests.auth.test_oauth_consent import form_transaction

VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


async def get_code(authed: AsyncClient, params: dict[str, str], **over: str) -> str:
    params = params | {"code_challenge": CHALLENGE} | over
    page = await authed.get("/oauth/authorize", params=params)
    consent = await authed.post(
        "/oauth/authorize/consent",
        data={"transaction": form_transaction(page), "decision": "approve"},
    )
    assert consent.status_code == 303, consent.text
    return parse_qs(urlsplit(consent.headers["location"]).query)["code"][0]


async def exchange(client: AsyncClient, code: str, params: dict[str, str], **over: str) -> Response:
    data = {
        "grant_type": "authorization_code",
        "client_id": params["client_id"],
        "code": code,
        "code_verifier": VERIFIER,
        "redirect_uri": CALLBACK,
        "resource": f"{ISSUER}/mcp",
    } | over
    return await client.post("/oauth/token", data=data)


async def refresh(client: AsyncClient, params: dict[str, str], token: str, **over: str) -> Response:
    data = {
        "grant_type": "refresh_token",
        "client_id": params["client_id"],
        "refresh_token": token,
    } | over
    return await client.post("/oauth/token", data=data)


@pytest.fixture
async def tokens(authed: AsyncClient, auth_params: dict[str, str]) -> dict[str, object]:
    response = await exchange(authed, await get_code(authed, auth_params), auth_params)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_code_exchange_issues_tokens(
    authed: AsyncClient,
    auth_params: dict[str, str],
    engine: AsyncEngine,
) -> None:
    response = await exchange(authed, await get_code(authed, auth_params), auth_params)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "films:read films:write"
    async with AsyncSession(engine) as db:
        row = (await db.scalars(select(OAuthToken))).one()
        assert row.access_token_hash != body["access_token"]
        assert body["access_token"] not in (row.access_token_hash, row.refresh_token_hash)
        assert row.resource == f"{ISSUER}/mcp"
        assert row.access_expires_at - row.created_at == timedelta(seconds=3600)


async def test_wrong_code_verifier_rejected(
    authed: AsyncClient,
    auth_params: dict[str, str],
) -> None:
    code = await get_code(authed, auth_params)
    response = await exchange(authed, code, auth_params, code_verifier="w" * 64)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    # The failed attempt spent the code.
    assert (await exchange(authed, code, auth_params)).status_code == 400


async def test_code_cannot_be_used_twice(
    authed: AsyncClient,
    auth_params: dict[str, str],
) -> None:
    code = await get_code(authed, auth_params)
    assert (await exchange(authed, code, auth_params)).status_code == 200
    again = await exchange(authed, code, auth_params)
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("redirect_uri", "https://client.example/other", "invalid_grant"),
        ("resource", "https://other.example/mcp", "invalid_target"),
    ],
)
async def test_code_bound_to_redirect_and_resource(
    authed: AsyncClient,
    auth_params: dict[str, str],
    field: str,
    value: str,
    error: str,
) -> None:
    code = await get_code(authed, auth_params)
    response = await exchange(authed, code, auth_params, **{field: value})
    assert response.status_code == 400
    assert response.json()["error"] == error


async def test_code_expires(
    authed: AsyncClient,
    auth_params: dict[str, str],
    engine: AsyncEngine,
) -> None:
    code = await get_code(authed, auth_params)
    async with AsyncSession(engine) as db:
        await db.execute(update(OAuthCode).values(expires_at=datetime.now(UTC) - timedelta(1)))
        await db.commit()
    assert (await exchange(authed, code, auth_params)).status_code == 400


async def test_unknown_client_and_grant(authed: AsyncClient, auth_params: dict[str, str]) -> None:
    unknown = await authed.post(
        "/oauth/token", data={"grant_type": "refresh_token", "client_id": "nope"}
    )
    assert unknown.status_code == 401
    grant = await authed.post(
        "/oauth/token", data={"grant_type": "password", "client_id": auth_params["client_id"]}
    )
    assert grant.json()["error"] == "unsupported_grant_type"


async def test_refresh_rotates_and_old_refresh_fails(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
) -> None:
    first = await refresh(authed, auth_params, tokens["refresh_token"])
    assert first.status_code == 200
    new = first.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert new["access_token"] != tokens["access_token"]
    assert (await refresh(authed, auth_params, tokens["refresh_token"])).status_code == 400
    # The family was revoked by the replay, so even the newest refresh token is dead.
    assert (await refresh(authed, auth_params, new["refresh_token"])).status_code == 400


async def test_replayed_refresh_revokes_family(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
    engine: AsyncEngine,
) -> None:
    new = (await refresh(authed, auth_params, tokens["refresh_token"])).json()
    await refresh(authed, auth_params, tokens["refresh_token"])
    async with AsyncSession(engine) as db:
        rows = (await db.scalars(select(OAuthToken))).all()
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)
    assert new["refresh_token"]


async def test_access_token_expires_after_3600s(
    authed: AsyncClient,
    tokens: dict[str, str],
    engine: AsyncEngine,
) -> None:
    assert tokens["expires_in"] == 3600
    async with AsyncSession(engine) as db:
        row = (await db.scalars(select(OAuthToken))).one()
        assert row.access_expires_at - row.created_at == timedelta(seconds=3600)


async def test_expired_refresh_token_rejected(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine) as db:
        await db.execute(
            update(OAuthToken).values(refresh_expires_at=datetime.now(UTC) - timedelta(1))
        )
        await db.commit()
    assert (await refresh(authed, auth_params, tokens["refresh_token"])).status_code == 400


async def test_scopes_cannot_widen_on_refresh(
    authed: AsyncClient,
    auth_params: dict[str, str],
) -> None:
    read_only = await get_code(authed, auth_params, scope="films:read")
    issued = (await exchange(authed, read_only, auth_params)).json()
    assert issued["scope"] == "films:read"
    widened = await refresh(
        authed, auth_params, issued["refresh_token"], scope="films:read films:write"
    )
    assert widened.status_code == 400
    assert widened.json()["error"] == "invalid_scope"


async def test_refresh_can_narrow_scope(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
) -> None:
    narrowed = await refresh(authed, auth_params, tokens["refresh_token"], scope="films:read")
    assert narrowed.status_code == 200
    assert narrowed.json()["scope"] == "films:read"


async def test_revoke_kills_token(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
    engine: AsyncEngine,
) -> None:
    response = await authed.post(
        "/oauth/revoke",
        data={"token": tokens["access_token"], "client_id": auth_params["client_id"]},
    )
    assert response.status_code == 200
    assert (await refresh(authed, auth_params, tokens["refresh_token"])).status_code == 400
    async with AsyncSession(engine) as db:
        assert all(r.revoked_at is not None for r in (await db.scalars(select(OAuthToken))).all())


async def test_revoke_unknown_token_is_ok_and_other_client_cannot_revoke(
    authed: AsyncClient,
    auth_params: dict[str, str],
    tokens: dict[str, str],
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine) as db:
        db.add(OAuthClient(id="other", name="Other", redirect_uris=[CALLBACK]))
        await db.commit()
    unknown = await authed.post("/oauth/revoke", data={"token": "x", "client_id": "other"})
    assert unknown.status_code == 200
    await authed.post(
        "/oauth/revoke", data={"token": tokens["refresh_token"], "client_id": "other"}
    )
    assert (await refresh(authed, auth_params, tokens["refresh_token"])).status_code == 200
