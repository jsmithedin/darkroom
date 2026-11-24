from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import Mount

from app.api import audit as audit_api
from app.api import auth as auth_api
from app.api import bulk as bulk_api
from app.api import devtimes as devtimes_api
from app.api import docs as docs_api
from app.api import export as export_api
from app.api import oauth as oauth_api
from app.api import reference as reference_api
from app.api import rolls as rolls_api
from app.api import settings as settings_api
from app.api import stats as stats_api
from app.api import stock as stock_api
from app.api import tokens as tokens_api
from app.auth.google import GoogleOIDC
from app.auth.oauth_server import oauth_metadata_routes
from app.config import Settings
from app.db import make_engine
from app.mcp.server import build_mcp, transport_security
from app.services.stock import InsufficientStockError, StocktakeChangedError
from app.spa import RootApp


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    mcp = build_mcp(settings, lambda: app.state.engine)
    mcp_app = mcp.streamable_http_app(transport_security=transport_security(settings))
    # Ours go first: the SDK's own protected-resource document lists only the required scope,
    # but clients must also learn that films:write exists.
    mcp_app.routes[0:0] = oauth_metadata_routes(settings.public_base_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # FastAPI does not run a mounted sub-app's lifespan, so enter the MCP one here.
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await app.state.engine.dispose()

    # The built-in docs are public; they are re-served behind sign-in by `api/docs.py`.
    app = FastAPI(
        title="Darkroom", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(StocktakeChangedError)
    async def stocktake_changed(_: Request, exc: StocktakeChangedError) -> JSONResponse:
        """409 listing the rows whose stock moved since the counts were reviewed."""
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "code": "stock_changed",
                "rows": [
                    {
                        "film_id": str(r.film_id),
                        "format_id": str(r.format_id),
                        "film": r.film_name,
                        "format": r.format_name,
                        "expected": r.expected,
                        "current": r.current,
                    }
                    for r in exc.rows
                ],
            },
        )

    @app.exception_handler(InsufficientStockError)
    async def insufficient_stock(_: Request, exc: InsufficientStockError) -> JSONResponse:
        """409 with enough detail for the UI to offer a recount of that film and format."""
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "code": "insufficient_stock",
                "film_id": str(exc.film_id),
                "format_id": str(exc.format_id),
                "film": exc.film_name,
                "format": exc.format_name,
                "available": exc.available,
            },
        )

    app.state.settings = settings
    app.state.oidc = GoogleOIDC(
        settings.google_client_id,
        settings.google_client_secret,
        f"{settings.public_base_url.rstrip('/')}/api/auth/callback",
    )
    app.include_router(auth_api.router)
    app.include_router(oauth_api.router)
    app.include_router(tokens_api.router)
    app.include_router(reference_api.router)
    app.include_router(rolls_api.router)
    app.include_router(settings_api.router)
    app.include_router(stock_api.router)
    app.include_router(stats_api.router)
    app.include_router(bulk_api.router)
    app.include_router(devtimes_api.router)
    app.include_router(audit_api.router)
    app.include_router(export_api.router)
    app.include_router(docs_api.router)
    app.state.engine = make_engine(settings.database_url)

    @app.get("/api/health")
    async def health() -> JSONResponse:
        engine: AsyncEngine = app.state.engine
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "error", "db": False}, status_code=503)
        return JSONResponse({"status": "ok", "db": True})

    # Last, so the app's own routes win. RootApp hands /mcp and /.well-known to the MCP app
    # and serves the built frontend (with SPA fallback) for everything else.
    app.router.routes.append(Mount("/", app=RootApp(mcp_app, Path(settings.frontend_dist))))

    return app
