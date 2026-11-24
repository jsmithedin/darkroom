from datetime import UTC, datetime, timedelta

from tests.mcp.conftest import HEADERS, INIT, RESOURCE, McpEnv

METADATA = "https://film.jamielab.uk/.well-known/oauth-protected-resource/mcp"


async def test_no_token_401_with_resource_metadata_header(mcp_env: McpEnv) -> None:
    async with mcp_env.client() as c:
        resp = await c.post("/mcp", headers=HEADERS, json=INIT)
    assert resp.status_code == 401
    challenge = resp.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{METADATA}"' in challenge


async def test_pat_accepted_on_mcp(mcp_env: McpEnv) -> None:
    assert (await mcp_env.initialize(await mcp_env.pat("films:read"))).status_code == 200


async def test_write_only_pat_satisfies_read_requirement(mcp_env: McpEnv) -> None:
    assert (await mcp_env.initialize(await mcp_env.pat("films:write"))).status_code == 200


async def test_oauth_token_accepted_on_mcp(mcp_env: McpEnv) -> None:
    token = await mcp_env.oauth_token("films:read")
    assert (await mcp_env.initialize(token)).status_code == 200


async def test_token_for_other_audience_rejected(mcp_env: McpEnv) -> None:
    token = await mcp_env.oauth_token("films:read", resource="https://other.example/mcp")
    assert (await mcp_env.initialize(token)).status_code == 401


async def test_expired_and_revoked_rejected(mcp_env: McpEnv) -> None:
    expired = await mcp_env.oauth_token("films:read", expires_in=timedelta(seconds=-1))
    revoked = await mcp_env.oauth_token("films:read", revoked=True)
    past = datetime.now(UTC) - timedelta(days=1)
    expired_pat = await mcp_env.pat("films:read", expires_at=past)
    for token in (expired, revoked, expired_pat, "drk_unknown", "dro_unknown", "junk"):
        assert (await mcp_env.initialize(token)).status_code == 401, token


async def test_token_never_accepted_in_query_string(mcp_env: McpEnv) -> None:
    token = await mcp_env.pat("films:read")
    async with mcp_env.client() as c:
        resp = await c.post(f"/mcp?access_token={token}", headers=HEADERS, json=INIT)
    assert resp.status_code == 401


async def test_oauth_token_not_accepted_on_rest_api(mcp_env: McpEnv) -> None:
    """OAuth tokens are bound to /mcp; the REST API takes personal access tokens only."""
    token = await mcp_env.oauth_token("films:read", "films:write")
    async with mcp_env.client(token) as c:
        assert (await c.get("/api/rolls")).status_code == 401
    pat = await mcp_env.pat("films:read")
    async with mcp_env.client(pat) as c:
        assert (await c.get("/api/rolls")).status_code == 200


async def test_protected_resource_metadata_lists_both_scopes(mcp_env: McpEnv) -> None:
    async with mcp_env.client() as c:
        resp = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.json()["scopes_supported"] == ["films:read", "films:write"]
    assert resp.json()["resource"] == RESOURCE
