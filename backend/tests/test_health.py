from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": True}


async def test_health_db_down() -> None:
    settings = Settings(database_url="postgresql+asyncpg://x:x@127.0.0.1:1/none")
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/health")
    assert resp.status_code == 503
    assert resp.json()["db"] is False
