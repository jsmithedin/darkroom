"""API documentation, for signed-in users only.

FastAPI's built-in `/docs`, `/redoc` and `/openapi.json` are public and list every endpoint,
so they are switched off in `create_app` and served here behind the normal read scope instead.
Browsers use their session cookie; scripts can send a bearer token.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth.principal import READ, Principal, require_scope

router = APIRouter(prefix="/api", include_in_schema=False)

Reader = Annotated[Principal, Depends(require_scope(READ))]


@router.get("/openapi.json")
async def openapi_schema(request: Request, _: Reader) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.get("/docs")
async def swagger_ui(_: Reader) -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Darkroom API")


@router.get("/redoc")
async def redoc(_: Reader) -> HTMLResponse:
    return get_redoc_html(openapi_url="/api/openapi.json", title="Darkroom API")
