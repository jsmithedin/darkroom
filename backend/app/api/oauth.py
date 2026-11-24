import html
import re
import uuid
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_oidc, get_settings, start_google_login
from app.auth.csrf import check_csrf
from app.auth.google import OIDCProvider
from app.auth.identity import READ, WRITE
from app.auth.oauth_server import (
    AUTHORIZE_PATH,
    GRANT_TYPES,
    REGISTRATION_WINDOW,
    RESPONSE_TYPES,
    AuthorizationRequest,
    RegistrationRequest,
    authorization_server_metadata,
    issue_authorization_code,
    register_client,
    valid_redirect_uri,
)
from app.auth.principal import browser_principal
from app.config import Settings
from app.db import get_session
from app.models import OAuthClient

router = APIRouter(tags=["oauth"])
DB = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
CONSENT_AGE = 600
REGISTRATION_MAX_BYTES = 16_384
AUTHORIZATION_QUERY_MAX_BYTES = 2_400
CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "same-origin"}
REGISTRATION_CORS = {"Access-Control-Allow-Origin": "*"}
SCOPE_DESCRIPTION = {
    READ: "Read your film records and stock",
    WRITE: "Record and edit your film data, including read access",
}


class Consent(BaseModel):
    id: uuid.UUID
    csrf_token: str
    authorization: AuthorizationRequest


def consent_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="oauth-consent")


def oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers=PRIVATE_HEADERS,
    )


def client_redirect(
    authorization: AuthorizationRequest, issuer: str, status: int = 302, **parameters: str
) -> RedirectResponse:
    if authorization.state is not None:
        parameters["state"] = authorization.state
    parameters["iss"] = issuer
    parts = urlsplit(authorization.redirect_uri)
    query = "&".join(filter(None, (parts.query, urlencode(parameters))))
    return RedirectResponse(
        urlunsplit(parts._replace(query=query)), status_code=status, headers=PRIVATE_HEADERS
    )


async def registered_client(
    db: AsyncSession, authorization: AuthorizationRequest
) -> OAuthClient | None:
    if not CLIENT_ID.fullmatch(authorization.client_id):
        return None
    client = await db.get(OAuthClient, authorization.client_id)
    if client is None or authorization.redirect_uri not in client.redirect_uris:
        return None
    return client if valid_redirect_uri(authorization.redirect_uri) else None


@router.options("/oauth/register", include_in_schema=False)
async def registration_preflight() -> Response:
    return Response(
        status_code=204,
        headers=REGISTRATION_CORS
        | {
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version",
        },
    )


@router.post("/oauth/register", status_code=201)
async def register(request: Request, db: DB) -> JSONResponse:
    response = await registration_response(request, db)
    response.headers.update(REGISTRATION_CORS)
    response.headers["Access-Control-Expose-Headers"] = "Retry-After"
    return response


async def registration_response(request: Request, db: AsyncSession) -> JSONResponse:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        return oauth_error("invalid_client_metadata", "Send a JSON registration document.", 415)

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > REGISTRATION_MAX_BYTES:
            return oauth_error(
                "invalid_client_metadata", "Registration document is too large.", 413
            )
        body.extend(chunk)
    try:
        client_metadata = RegistrationRequest.model_validate_json(body)
    except ValidationError:
        return oauth_error("invalid_client_metadata", "The client metadata is invalid.")
    if client_metadata.software_statement is not None:
        return oauth_error("unapproved_software_statement", "Software statements are unsupported.")
    if "authorization_code" not in client_metadata.grant_types or any(
        ord(char) < 32 or ord(char) == 127 for char in client_metadata.client_name
    ):
        return oauth_error("invalid_client_metadata", "The client metadata is invalid.")
    if any(not valid_redirect_uri(uri) for uri in client_metadata.redirect_uris):
        return oauth_error(
            "invalid_redirect_uri", "Use a valid HTTPS or HTTP loopback redirect URI."
        )

    client = await register_client(db, client_metadata)
    if client is None:
        response = oauth_error(
            "temporarily_unavailable", "Too many registrations. Try again later.", 429
        )
        response.headers["Retry-After"] = str(int(REGISTRATION_WINDOW.total_seconds()))
        return response
    return JSONResponse(
        {
            "client_id": client.id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": GRANT_TYPES,
            "response_types": RESPONSE_TYPES,
        },
        status_code=201,
        headers=PRIVATE_HEADERS,
    )


def consent_page(
    client: OAuthClient, authorization: AuthorizationRequest, transaction: str
) -> HTMLResponse:
    scopes = "".join(
        f"<li>{SCOPE_DESCRIPTION[scope]} (<code>{scope}</code>)</li>"
        for scope in authorization.scopes
    )
    redirect_host = urlsplit(authorization.redirect_uri).hostname or ""
    redirect = html.escape(authorization.redirect_uri)
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        "<title>Authorize Darkroom access</title>"
        "<style>body{font:1rem/1.6 system-ui;color-scheme:light dark}"
        "main{max-width:36rem;margin:3rem auto;padding:0 1rem}"
        "code{overflow-wrap:anywhere}button{font:inherit;min-height:44px;padding:.25rem 1rem}"
        "form{display:flex;flex-wrap:wrap;gap:.75rem}</style></head>"
        "<body><main><h1>Authorize Darkroom access</h1>"
        f"<p><strong>{html.escape(client.name)}</strong> requests access to Darkroom.</p>"
        f"<p><strong>Redirect host</strong> {html.escape(redirect_host)}<br>"
        f"<strong>Redirect URI</strong> <code>{redirect}</code></p>"
        f"<h2>Permissions</h2><ul>{scopes}</ul>"
        '<form method="post" action="/oauth/authorize/consent">'
        f'<input type="hidden" name="transaction" value="{html.escape(transaction)}">'
        '<button type="submit" name="decision" value="approve">Allow access</button>'
        '<button type="submit" name="decision" value="deny">Deny</button>'
        "</form></main></body></html>",
        headers=PRIVATE_HEADERS
        | {
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
        },
    )


@router.get(AUTHORIZE_PATH, response_model=None)
async def authorize(
    request: Request, db: DB, settings: Config, oidc: Annotated[OIDCProvider, Depends(get_oidc)]
) -> Response:
    params = request.query_params
    if len(request.scope["query_string"]) > AUTHORIZATION_QUERY_MAX_BYTES or any(
        len(params.getlist(key)) > 1 for key in AuthorizationRequest.model_fields
    ):
        return oauth_error("invalid_request", "The authorization request is invalid.")
    try:
        authorization = AuthorizationRequest.model_validate(dict(params))
    except ValidationError:
        return oauth_error("invalid_request", "The client and redirect URI are required.")

    client = await registered_client(db, authorization)
    if client is None:
        return oauth_error("invalid_request", "Unknown client or redirect URI.")

    issuer = str(authorization_server_metadata(settings.public_base_url).issuer)
    error = authorization.error(issuer)
    if error is not None:
        return client_redirect(authorization, issuer, error=error[0], error_description=error[1])

    principal = await browser_principal(request, db)
    if principal is None:
        query = urlencode(authorization.model_dump(exclude_none=True))
        if len(query) > AUTHORIZATION_QUERY_MAX_BYTES:
            return oauth_error("invalid_request", "The authorization request is too large.")
        # Release the connection before initiating the sign-in provider's network request.
        await db.rollback()
        login = await start_google_login(settings, oidc, oauth_query=query)
        login.headers.update(PRIVATE_HEADERS)
        return login

    assert principal.csrf_token is not None
    consent = Consent(id=uuid.uuid4(), csrf_token=principal.csrf_token, authorization=authorization)
    return consent_page(
        client, authorization, consent_serializer(settings).dumps(consent.model_dump(mode="json"))
    )


@router.post("/oauth/authorize/consent", response_model=None)
async def submit_consent(
    request: Request,
    db: DB,
    settings: Config,
    transaction: Annotated[str, Form(max_length=4096)],
    decision: Annotated[Literal["approve", "deny"], Form()],
) -> Response:
    principal = await browser_principal(request, db)
    if principal is None:
        return oauth_error("login_required", "Sign in before approving access.", 401)
    try:
        consent = Consent.model_validate(
            consent_serializer(settings).loads(transaction, max_age=CONSENT_AGE)
        )
    except (BadSignature, ValidationError):
        return oauth_error("invalid_request", "The consent request is invalid or expired.")
    assert principal.csrf_token is not None
    check_csrf(request, principal.csrf_token, form_token=consent.csrf_token)

    authorization = consent.authorization
    if await registered_client(db, authorization) is None:
        return oauth_error("invalid_request", "Unknown client or redirect URI.")
    issuer = str(authorization_server_metadata(settings.public_base_url).issuer)
    error = authorization.error(issuer)
    if error is not None:
        return client_redirect(
            authorization, issuer, 303, error=error[0], error_description=error[1]
        )
    if decision == "deny":
        return client_redirect(authorization, issuer, 303, error="access_denied")
    code = await issue_authorization_code(db, authorization, principal.user_id, consent.id)
    if code is None:
        return oauth_error("invalid_request", "This request has already been approved.")
    return client_redirect(authorization, issuer, 303, code=code)
