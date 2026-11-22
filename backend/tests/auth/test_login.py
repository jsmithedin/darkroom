import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.google import Identity
from app.models import User, UserSession
from tests.support import ORIGIN, FakeOIDC, sign_in, start_login

pytestmark = pytest.mark.usefixtures("oidc")


async def count(engine: AsyncEngine, model: type) -> int:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_allowed_email_gets_session_cookie(client: AsyncClient, engine: AsyncEngine) -> None:
    state = await start_login(client)
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    cookie = next(
        c for c in resp.headers.get_list("set-cookie") if c.startswith("darkroom_session=")
    ).lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert await count(engine, UserSession) == 1
    me = await client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "me@example.com"


async def test_session_cookie_is_not_stored_raw(client: AsyncClient, engine: AsyncEngine) -> None:
    await sign_in(client)
    raw = client.cookies["darkroom_session"]
    async with AsyncSession(engine) as s:
        stored = (await s.execute(select(UserSession.token_hash))).scalar_one()
    assert stored != raw
    assert len(stored) == 64


async def test_allowlist_is_case_insensitive_and_upserts_user(
    client: AsyncClient, oidc: FakeOIDC, engine: AsyncEngine
) -> None:
    oidc.identity = Identity(sub="sub-1", email="ME@Example.com", email_verified=True, name="Me")
    await sign_in(client)
    oidc.identity = Identity(sub="sub-1", email="me@example.com", email_verified=True, name="New")
    await sign_in(client)
    assert await count(engine, User) == 1
    assert (await client.get("/api/me")).json()["name"] == "New"


async def test_unlisted_email_refused_with_message_and_no_session(
    client: AsyncClient, oidc: FakeOIDC, engine: AsyncEngine
) -> None:
    oidc.identity = Identity(sub="s2", email="eve@example.com", email_verified=True, name="Eve")
    state = await start_login(client)
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 403
    assert "not authorised" in resp.text
    assert "darkroom_session" not in resp.headers.get("set-cookie", "")
    assert await count(engine, UserSession) == 0
    assert await count(engine, User) == 0
    assert (await client.get("/api/me")).status_code == 401


async def test_unverified_email_refused(
    client: AsyncClient, oidc: FakeOIDC, engine: AsyncEngine
) -> None:
    oidc.identity = Identity(sub="s1", email="me@example.com", email_verified=False, name="Me")
    state = await start_login(client)
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 403
    assert await count(engine, UserSession) == 0


async def test_state_mismatch_rejected(client: AsyncClient, engine: AsyncEngine) -> None:
    await start_login(client)
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": "forged"})
    assert resp.status_code == 400
    assert await count(engine, UserSession) == 0


async def test_callback_without_login_cookie_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": "x"})
    assert resp.status_code == 400


async def test_bad_provider_response_rejected(client: AsyncClient, oidc: FakeOIDC) -> None:
    state = await start_login(client)
    oidc.fail = True
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 400
    assert (await client.get("/api/me")).status_code == 401


async def test_post_without_csrf_header_is_403(client: AsyncClient) -> None:
    await sign_in(client)
    resp = await client.post("/api/auth/logout", headers=ORIGIN)
    assert resp.status_code == 403
    assert (await client.get("/api/me")).status_code == 200


async def test_post_with_wrong_origin_is_403(client: AsyncClient) -> None:
    await sign_in(client)
    token = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": token, "Origin": "https://evil.example"}
    )
    assert resp.status_code == 403


async def test_post_with_csrf_header_succeeds(client: AsyncClient) -> None:
    await sign_in(client)
    token = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.post("/api/auth/logout", headers={"X-CSRF-Token": token, **ORIGIN})
    assert resp.status_code == 204


async def test_logout_invalidates_session(client: AsyncClient, engine: AsyncEngine) -> None:
    await sign_in(client)
    raw = client.cookies["darkroom_session"]
    token = (await client.get("/api/me")).json()["csrf_token"]
    await client.post("/api/auth/logout", headers={"X-CSRF-Token": token, **ORIGIN})
    assert await count(engine, UserSession) == 0
    # replaying the old cookie no longer works
    client.cookies.set("darkroom_session", raw)
    assert (await client.get("/api/me")).status_code == 401
