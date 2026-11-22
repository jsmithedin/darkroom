from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient

from app.auth.google import Identity, LoginError
from app.auth.principal import READ, WRITE, Principal, require_scope


class FakeOIDC:
    """Stands in for Google: the test decides who 'signs in'."""

    def __init__(self) -> None:
        self.identity = Identity(
            sub="sub-1", email="me@example.com", email_verified=True, name="Me"
        )
        self.fail = False
        self.last_nonce: str | None = None

    async def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str:
        self.last_nonce = nonce
        return f"https://accounts.example/auth?state={state}"

    async def exchange(self, code: str, code_verifier: str, nonce: str) -> Identity:
        if self.fail or nonce != self.last_nonce:
            raise LoginError("bad")
        return self.identity


@pytest.fixture
def oidc(client: AsyncClient) -> FakeOIDC:
    fake = FakeOIDC()
    client._transport.app.state.oidc = fake  # type: ignore[attr-defined]
    return fake


async def start_login(client: AsyncClient) -> str:
    """Hit /login and return the `state` the app sent to the provider."""
    resp = await client.get("/api/auth/login")
    assert resp.status_code == 302
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


async def sign_in(client: AsyncClient) -> None:
    state = await start_login(client)
    resp = await client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 302


ORIGIN = {"Origin": "https://film.jamielab.uk"}


def scoped_routes() -> APIRouter:
    """Throwaway routes that need each scope, to test enforcement."""
    router = APIRouter(prefix="/api/_test")

    @router.get("/read")
    async def read(p: Principal = Depends(require_scope(READ))) -> dict[str, str]:  # noqa: B008
        return {"via": p.via}

    @router.post("/write")
    async def write(p: Principal = Depends(require_scope(WRITE))) -> dict[str, str]:  # noqa: B008
        return {"via": p.via}

    return router


def mount_routes(app: FastAPI, router: APIRouter) -> None:
    """Add routes ahead of the catch-all mount that `create_app` puts last."""
    app.include_router(router)
    app.router.routes.append(app.router.routes.pop(-2))


@pytest.fixture
def scoped(client: AsyncClient) -> None:
    mount_routes(client._transport.app, scoped_routes())  # type: ignore[attr-defined]


async def make_token(client: AsyncClient, scopes: list[str], **extra: object) -> dict[str, object]:
    """Sign in, create a PAT through the API, then drop the cookie so only the token remains."""
    await sign_in(client)
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    resp = await client.post(
        "/api/tokens",
        json={"name": "t", "scopes": scopes, **extra},
        headers={"X-CSRF-Token": csrf, **ORIGIN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]
