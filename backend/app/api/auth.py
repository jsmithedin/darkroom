import hmac
import html
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import LoginError, OIDCProvider, new_code_verifier
from app.auth.oauth_server import AUTHORIZE_PATH
from app.auth.principal import Principal, current_principal
from app.auth.sessions import ABSOLUTE, SESSION_COOKIE, create_session, delete_session
from app.config import Settings
from app.db import get_session
from app.models import User

router = APIRouter(prefix="/api")

OIDC_COOKIE = "darkroom_oidc"
OIDC_MAX_AGE = 600
COOKIE_PATH = "/api/auth"


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_oidc(request: Request) -> OIDCProvider:
    oidc: OIDCProvider = request.app.state.oidc
    return oidc


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="oidc-login")


def _page(message: str, status: int, *, retry: str = "/api/auth/login") -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Darkroom</title>"
        "<main style='font-family:system-ui;max-width:30rem;margin:3rem auto;padding:0 1rem'>"
        f"<h1>Darkroom</h1><p>{html.escape(message)}</p>"
        f"<p><a href='{html.escape(retry)}'>Try again</a></p></main>"
    )
    return HTMLResponse(
        body,
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin"},
    )


@router.get("/auth/login")
async def login(
    settings: Annotated[Settings, Depends(get_settings)],
    oidc: Annotated[OIDCProvider, Depends(get_oidc)],
) -> RedirectResponse:
    return await start_google_login(settings, oidc)


async def start_google_login(
    settings: Settings, oidc: OIDCProvider, *, oauth_query: str | None = None
) -> RedirectResponse:
    state, nonce, verifier = (
        secrets.token_urlsafe(24),
        secrets.token_urlsafe(24),
        new_code_verifier(),
    )
    url = await oidc.authorization_url(state, nonce, verifier)
    resp = RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    transaction = {"s": state, "n": nonce, "v": verifier}
    if oauth_query is not None:
        transaction["oauth_query"] = oauth_query
    resp.set_cookie(
        OIDC_COOKIE,
        _serializer(settings).dumps(transaction),
        max_age=OIDC_MAX_AGE,
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/auth/callback", response_model=None)
async def callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    oidc: Annotated[OIDCProvider, Depends(get_oidc)],
    db: Annotated[AsyncSession, Depends(get_session)],
    code: str = "",
    state: str = "",
    error: str = "",
) -> Response:
    try:
        txn = _serializer(settings).loads(
            request.cookies.get(OIDC_COOKIE, ""), max_age=OIDC_MAX_AGE
        )
    except BadSignature:
        if error:
            return _page("Sign-in was cancelled or failed.", 400)
        return _page("Sign-in session expired. Please try again.", 400)
    if not hmac.compare_digest(state.encode(), str(txn["s"]).encode()):
        return _page("Sign-in could not be verified. Please try again.", 400)
    oauth_query = txn.get("oauth_query")
    oauth_continue = f"{AUTHORIZE_PATH}?{oauth_query}" if oauth_query else None
    retry = oauth_continue or "/api/auth/login"
    if error:
        return _page("Sign-in was cancelled or failed.", 400, retry=retry)
    if not code:
        return _page("Sign-in could not be verified. Please try again.", 400, retry=retry)

    try:
        identity = await oidc.exchange(code, txn["v"], txn["n"])
    except LoginError:
        return _page("Sign-in could not be verified. Please try again.", 400, retry=retry)
    if not identity.email_verified:
        return _page("Your Google email address is not verified.", 403, retry=retry)
    if identity.email.lower() not in {e.lower() for e in settings.allowed_emails}:
        return _page("This Google account is not authorised to use Darkroom.", 403, retry=retry)

    user = (
        await db.execute(select(User).where(User.google_sub == identity.sub))
    ).scalar_one_or_none()
    if user is None:
        user = User(email=identity.email, name=identity.name, google_sub=identity.sub)
        db.add(user)
        await db.flush()
    else:
        user.email, user.name = identity.email, identity.name
    raw = await create_session(db, user)

    resp = RedirectResponse(
        oauth_continue or "/", status_code=302, headers={"Cache-Control": "no-store"}
    )
    resp.delete_cookie(OIDC_COOKIE, path=COOKIE_PATH)
    resp.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=int(ABSOLUTE.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    _: Annotated[Principal, Depends(current_principal)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        await delete_session(db, raw)
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


class Me(BaseModel):
    email: str
    name: str
    csrf_token: str


@router.get("/me")
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Me:
    user = await db.get(User, principal.user_id)
    assert user is not None and principal.csrf_token is not None
    return Me(email=user.email, name=user.name, csrf_token=principal.csrf_token)
