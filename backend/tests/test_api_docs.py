from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

PUBLIC_PATHS = ["/openapi.json", "/docs", "/redoc"]
PRIVATE_PATHS = ["/api/openapi.json", "/api/docs", "/api/redoc"]


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_default_docs_paths_no_longer_expose_the_api(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    # not found, or the frontend's index page: either way, no endpoint list
    assert "/api/rolls" not in resp.text
    assert '"openapi"' not in resp.text
    assert "swagger" not in resp.text.lower()


@pytest.mark.parametrize("path", PRIVATE_PATHS)
async def test_docs_need_sign_in(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status_code == 401
    assert "/api/rolls" not in resp.text


async def test_signed_in_user_gets_the_schema(authed: AsyncClient) -> None:
    resp = await authed.get("/api/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "Darkroom"
    assert "/api/rolls" in schema["paths"]
    assert "/api/stock" in schema["paths"]
    # the docs routes describe the API, not themselves
    assert "/api/docs" not in schema["paths"]
    assert "/api/openapi.json" not in schema["paths"]


async def test_signed_in_user_gets_the_pages(authed: AsyncClient) -> None:
    swagger = await authed.get("/api/docs")
    assert swagger.status_code == 200
    assert "text/html" in swagger.headers["content-type"]
    assert "/api/openapi.json" in swagger.text
    redoc = await authed.get("/api/redoc")
    assert redoc.status_code == 200
    assert "/api/openapi.json" in redoc.text


async def test_a_read_token_can_fetch_the_schema(
    authed: AsyncClient, bearer_client: Callable[..., Awaitable[AsyncClient]]
) -> None:
    reader = await bearer_client("films:read")
    async with reader:
        assert (await reader.get("/api/openapi.json")).status_code == 200
