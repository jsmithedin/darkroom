import time
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.auth.google import LoginError, verify_id_token

CLIENT_ID = "client-123"
KEY = RSAKey.generate_key(2048, {"kid": "k1", "use": "sig"})
JWKS: dict[str, Any] = {"keys": [KEY.as_dict(private=False)]}


def make_token(key: RSAKey = KEY, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "abc",
        "email": "me@example.com",
        "email_verified": True,
        "name": "Me",
        "nonce": "n1",
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key)


def test_valid_token() -> None:
    ident = verify_id_token(make_token(), JWKS, CLIENT_ID, "n1")
    assert (ident.sub, ident.email, ident.email_verified) == ("abc", "me@example.com", True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "other"},
        {"aud": "someone-else"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 10},
        {"nonce": None},
    ],
)
def test_bad_claims_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(LoginError):
        verify_id_token(make_token(**overrides), JWKS, CLIENT_ID, "n1")


def test_wrong_signing_key_rejected() -> None:
    other = RSAKey.generate_key(2048, {"kid": "k1", "use": "sig"})
    with pytest.raises(LoginError):
        verify_id_token(make_token(key=other), JWKS, CLIENT_ID, "n1")


def test_unverified_email_is_reported_not_raised() -> None:
    ident = verify_id_token(make_token(email_verified=False), JWKS, CLIENT_ID, "n1")
    assert ident.email_verified is False
