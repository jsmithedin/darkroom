# MCP mount spike (Task 0.3)

Date: 2026-11-22. SDK: `mcp` 2.3.x, class `mcp.server.mcpserver.MCPServer`. Tests: `backend/tests/test_mcp_mount.py`.

## Result

`mcp.streamable_http_app(transport_security=...)` mounts in the FastAPI app with `Mount("/")` and works, provided the points below are respected.

## Findings

- **Lifespan.** FastAPI does not run a mounted sub-app's lifespan. Without it, `POST /mcp` raises `RuntimeError: Task group is not initialized. Make sure to use run().` The app's lifespan must enter `mcp.session_manager.run()` (done in `create_app`). `run()` can be entered once per `MCPServer` instance, so `create_app` builds a fresh `MCPServer` each call (tests rely on this).
- **Mount order.** The `Mount("/")` is appended after our own routes, so `/api/health` is not shadowed (`test_api_health_still_reachable`). Any route added to the FastAPI app later must go in before the mount: append the mount last, in `create_app`.
- **Mount path.** The SDK app serves `/mcp` itself (`streamable_http_path` defaults to `/mcp`), so mounting at `/` gives the endpoint `/mcp` with no redirect.
- **Host check.** `TransportSecuritySettings(allowed_hosts=[host, host:*], allowed_origins=[origin])` built from `PUBLIC_BASE_URL`. A request with another Host gets 421 (`test_wrong_host_rejected`). The default (localhost only) would reject the public hostname.
- **Responses** to `initialize` and `tools/list` may be SSE or JSON; test helper handles both.
- **Protected-resource well-known route** (probed with `auth=AuthSettings(...)` and a `token_verifier`): served at `/.well-known/oauth-protected-resource/mcp` (path-suffixed per RFC 9728), not at `/.well-known/oauth-protected-resource`, which 404s. The 401 from `/mcp` carries `WWW-Authenticate: Bearer error="invalid_token", ..., resource_metadata="https://<host>/.well-known/oauth-protected-resource/mcp"`. The metadata lists `authorization_servers`, `scopes_supported` and `bearer_methods_supported: ["header"]`.
- **FastAPI vs Starlette.** `streamable_http_app()` returns a plain Starlette app; mounting inside FastAPI behaves the same as inside Starlette apart from the lifespan point above.

## Differences from the spec (section 7)

- Spec said the well-known route location needed verifying: it is the path-suffixed form above. The Cloudflare WAF skip rule for `/.well-known/*` already covers it.
- `AuthSettings.validate_token_resource` is unset by default and warns that it defaults to True in 3.0. Phase 6 must set it explicitly (True if the SDK should check the audience, False if our `TokenVerifier` validates it).
- Spec's pin `mcp>=2.3,<3` resolved without trouble.
