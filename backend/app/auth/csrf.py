import hmac
from urllib.parse import urlparse

from fastapi import HTTPException, Request

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"


def check_csrf(request: Request, expected_token: str) -> None:
    """Reject cookie-authenticated unsafe requests without a valid Origin and CSRF header."""
    if request.method in SAFE_METHODS:
        return
    base = urlparse(request.app.state.settings.public_base_url)
    if request.headers.get("origin") != f"{base.scheme}://{base.netloc}":
        raise HTTPException(status_code=403, detail="Bad origin")
    supplied = request.headers.get(CSRF_HEADER, "")
    if not hmac.compare_digest(supplied.encode(), expected_token.encode()):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")
