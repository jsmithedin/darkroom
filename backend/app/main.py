from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import Mount

from app.config import Settings
from app.db import make_engine
from app.mcp.server import build_mcp, transport_security


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app(transport_security=transport_security(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # FastAPI does not run a mounted sub-app's lifespan, so enter the MCP one here.
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await app.state.engine.dispose()

    app = FastAPI(title="Darkroom", lifespan=lifespan)
    app.state.settings = settings
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

    # Last, so the app's own routes win; the MCP app serves /mcp and its well-known routes.
    app.router.routes.append(Mount("/", app=mcp_app))

    return app
