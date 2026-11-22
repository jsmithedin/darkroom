from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import PersonalAccessToken
from tests.auth.conftest import ORIGIN, make_token, sign_in

pytestmark = pytest.mark.usefixtures("oidc", "scoped")


def bearer(tok: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok['token']}"}


async def one_pat(engine: AsyncEngine) -> PersonalAccessToken:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(PersonalAccessToken))).scalar_one()


async def test_plaintext_not_stored(client: AsyncClient, engine: AsyncEngine) -> None:
    tok = await make_token(client, ["films:read"])
    raw = str(tok["token"])
    assert raw.startswith("drk_")
    pat = await one_pat(engine)
    assert pat.token_hash != raw
    assert len(pat.token_hash) == 64
    assert pat.prefix == raw[:8]
    assert len(pat.prefix) == 8
    # nothing in the row holds the secret part
    assert raw[8:] not in {pat.name, pat.prefix, pat.token_hash}


async def test_token_is_shown_only_on_create(client: AsyncClient) -> None:
    await make_token(client, ["films:read"])
    listed = (await client.get("/api/tokens")).json()
    assert len(listed) == 1
    assert "token" not in listed[0]
    assert listed[0]["prefix"].startswith("drk_")


async def test_valid_token_resolves_principal_with_scopes(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:read"])
    client.cookies.clear()
    resp = await client.get("/api/_test/read", headers=bearer(tok))
    assert resp.status_code == 200
    assert resp.json() == {"via": "pat"}


async def test_revoked_token_401(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:read"])
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.delete(f"/api/tokens/{tok['id']}", headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert resp.status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/_test/read", headers=bearer(tok))).status_code == 401


async def test_expired_token_401(client: AsyncClient, engine: AsyncEngine) -> None:
    tok = await make_token(client, ["films:read"])
    async with AsyncSession(engine) as s:
        await s.execute(
            update(PersonalAccessToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    client.cookies.clear()
    assert (await client.get("/api/_test/read", headers=bearer(tok))).status_code == 401


async def test_read_scope_cannot_hit_write_route_403(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:read"])
    client.cookies.clear()
    resp = await client.post("/api/_test/write", headers=bearer(tok))
    assert resp.status_code == 403
    assert "insufficient_scope" in resp.headers["www-authenticate"]


async def test_write_scope_implies_read(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:write"])
    client.cookies.clear()
    assert (await client.get("/api/_test/read", headers=bearer(tok))).status_code == 200
    assert (await client.post("/api/_test/write", headers=bearer(tok))).status_code == 200


async def test_last_used_at_updates(client: AsyncClient, engine: AsyncEngine) -> None:
    tok = await make_token(client, ["films:read"])
    assert (await one_pat(engine)).last_used_at is None
    client.cookies.clear()
    await client.get("/api/_test/read", headers=bearer(tok))
    used = (await one_pat(engine)).last_used_at
    assert used is not None
    assert datetime.now(UTC) - used < timedelta(seconds=30)


async def test_bearer_post_needs_no_csrf(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:write"])
    client.cookies.clear()
    resp = await client.post("/api/_test/write", headers=bearer(tok))  # no Origin, no CSRF
    assert resp.status_code == 200


@pytest.mark.parametrize("header", ["Bearer drk_nope", "Bearer", "Basic abc", "Bearer xyz"])
async def test_bad_authorization_header_401(client: AsyncClient, header: str) -> None:
    resp = await client.get("/api/_test/read", headers={"Authorization": header})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")


async def test_bad_bearer_does_not_fall_back_to_cookie(client: AsyncClient) -> None:
    await sign_in(client)
    assert (await client.get("/api/_test/read")).status_code == 200
    resp = await client.get("/api/_test/read", headers={"Authorization": "Bearer drk_bad"})
    assert resp.status_code == 401


async def test_unauthenticated_401(client: AsyncClient) -> None:
    assert (await client.get("/api/_test/read")).status_code == 401
    assert (await client.get("/api/tokens")).status_code == 401


async def test_token_cannot_manage_tokens(client: AsyncClient) -> None:
    tok = await make_token(client, ["films:write"])
    client.cookies.clear()
    assert (await client.get("/api/tokens", headers=bearer(tok))).status_code == 403
    resp = await client.post(
        "/api/tokens", headers=bearer(tok), json={"name": "x", "scopes": ["films:read"]}
    )
    assert resp.status_code == 403


async def test_create_requires_csrf(client: AsyncClient) -> None:
    await sign_in(client)
    resp = await client.post(
        "/api/tokens", json={"name": "x", "scopes": ["films:read"]}, headers=ORIGIN
    )
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "scopes": ["films:read"]},
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["films:delete"]},
        {"name": "x", "scopes": ["films:read"], "expires_at": "2001-01-01T00:00:00Z"},
        {"name": "x", "scopes": ["films:read"], "expires_at": "2999-01-01T00:00:00"},
    ],
)
async def test_create_validation(client: AsyncClient, body: dict[str, object]) -> None:
    await sign_in(client)
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.post("/api/tokens", json=body, headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert resp.status_code == 422


async def test_revoke_unknown_token_404(client: AsyncClient) -> None:
    await sign_in(client)
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.delete(
        "/api/tokens/00000000-0000-0000-0000-000000000000",
        headers={"X-CSRF-Token": csrf, **ORIGIN},
    )
    assert resp.status_code == 404


async def test_session_has_all_scopes(client: AsyncClient) -> None:
    await sign_in(client)
    assert (await client.get("/api/_test/read")).status_code == 200
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.post("/api/_test/write", headers={"X-CSRF-Token": csrf, **ORIGIN})
    assert resp.status_code == 200
