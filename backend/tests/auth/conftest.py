import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import OAuthClient

ISSUER = "https://film.jamielab.uk"
CALLBACK = "https://client.example/callback?mode=mcp"
CHALLENGE = "A" * 43


@pytest.fixture
async def auth_params(client: AsyncClient, engine: AsyncEngine) -> dict[str, str]:
    async with AsyncSession(engine) as db:
        db.add(OAuthClient(id="film-assistant", name="Film Assistant", redirect_uris=[CALLBACK]))
        await db.commit()
    return {
        "client_id": "film-assistant",
        "response_type": "code",
        "redirect_uri": CALLBACK,
        "scope": "films:read films:write",
        "state": "client-state",
        "resource": f"{ISSUER}/mcp",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }
