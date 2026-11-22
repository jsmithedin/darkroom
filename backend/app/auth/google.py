import secrets
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.jwk import KeySet

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    email_verified: bool
    name: str


class LoginError(Exception):
    """The provider response could not be trusted."""


class OIDCProvider(Protocol):
    async def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str: ...

    async def exchange(self, code: str, code_verifier: str, nonce: str) -> Identity: ...


def new_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def verify_id_token(id_token: str, jwks: dict[str, Any], client_id: str, nonce: str) -> Identity:
    """Check signature, issuer, audience, expiry and nonce, then return the identity."""
    try:
        keys = KeySet.import_key_set(jwks)  # type: ignore[arg-type]
        token = jwt.decode(id_token, keys, algorithms=["RS256"])
        claims = token.claims
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "values": list(ISSUERS)},
            aud={"essential": True, "value": client_id},
            exp={"essential": True},
            nonce={"essential": True, "value": nonce},
            sub={"essential": True},
        ).validate(claims)
    except Exception as exc:
        raise LoginError("Invalid ID token") from exc
    return Identity(
        sub=str(claims["sub"]),
        email=str(claims.get("email", "")),
        email_verified=claims.get("email_verified") is True,
        name=str(claims.get("name") or claims.get("email", "")),
    )


class GoogleOIDC:
    """Authorization code flow with PKCE against Google."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._metadata: dict[str, Any] | None = None

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.get(DISCOVERY_URL)
                resp.raise_for_status()
                self._metadata = resp.json()
        return self._metadata

    def _client(self) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope="openid email profile",
            code_challenge_method="S256",
            timeout=10,
        )

    async def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str:
        meta = await self._discover()
        async with self._client() as client:
            url, _ = client.create_authorization_url(
                meta["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
            )
        return str(url)

    async def exchange(self, code: str, code_verifier: str, nonce: str) -> Identity:
        meta = await self._discover()
        async with self._client() as client:
            token = await client.fetch_token(
                meta["token_endpoint"], code=code, code_verifier=code_verifier
            )
        id_token = token.get("id_token")
        if not id_token:
            raise LoginError("No ID token returned")
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(meta["jwks_uri"])
            resp.raise_for_status()
        return verify_id_token(id_token, resp.json(), self.client_id, nonce)
