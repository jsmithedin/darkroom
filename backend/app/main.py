from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db import make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    return app
