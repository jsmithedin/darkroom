from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.auth.google import Identity, LoginError


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
