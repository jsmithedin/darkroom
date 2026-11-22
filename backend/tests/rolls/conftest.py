import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
async def stocked(authed: AsyncClient, gear: dict[str, str]) -> None:
    """These tests are about rolls, not stock: hold plenty of every film/format they use."""
    for film in (gear["film"], gear["film2"]):
        for fmt in (gear["format35"], gear["format120"]):
            resp = await authed.post(
                "/api/stock-movements",
                json={
                    "kind": "opening",
                    "film_id": film,
                    "format_id": fmt,
                    "occurred_on": "2026-01-01",
                    "rolls": 100,
                },
            )
            assert resp.status_code == 201
