from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def spa_client(
    tmp_path: Path, test_settings: Settings, engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>darkroom</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(test_settings.model_copy(update={"frontend_dist": str(tmp_path)}))
    app.state.engine = engine
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://film.jamielab.uk"
    ) as c:
        yield c


async def test_spa_fallback_serves_index(spa_client: AsyncClient) -> None:
    for path in ["/", "/log", "/stock/some/deep/link"]:
        resp = await spa_client.get(path)
        assert resp.status_code == 200
        assert "darkroom" in resp.text
        assert resp.headers["content-type"].startswith("text/html")


async def test_static_asset_served(spa_client: AsyncClient) -> None:
    resp = await spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log(1)"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_missing_static_asset_returns_404(spa_client: AsyncClient, method: str) -> None:
    resp = await spa_client.request(method, "/assets/old-build.js")
    assert resp.status_code == 404


async def test_unknown_api_path_is_json_404(spa_client: AsyncClient) -> None:
    resp = await spa_client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


async def test_path_traversal_does_not_escape(spa_client: AsyncClient) -> None:
    resp = await spa_client.get("/..%2f..%2fetc/passwd")
    assert "root:" not in resp.text


async def test_hashed_assets_are_cached_for_a_year(spa_client: AsyncClient) -> None:
    resp = await spa_client.get("/assets/app.js")
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_index_must_be_revalidated(spa_client: AsyncClient) -> None:
    for path in ["/", "/index.html", "/stock/deep/link"]:
        resp = await spa_client.get(path)
        assert resp.headers["cache-control"] == "no-cache"
