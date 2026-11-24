# Frontend serving and native-client readiness (issue #55)

Reviewed 2026-11-24. This is a decision record; only the cache headers changed code.

## Decision 1: keep FastAPI serving the frontend

Keep one container and one origin. A separate nginx or Caddy container would
buy long-lived caching and independent frontend deploys, and costs an extra
container, a second config to keep in step with `spa.py`, and a change to the
tunnel route. The one real gain, caching, is now covered in the app (below).
The frontend is a few hundred kB for one user, so independent deploys are not
worth a service. A separate frontend hostname would need CORS and a cookie
domain and is rejected. Revisit if the frontend and API ever need different
release cycles.

## Decision 2: cache headers in `spa.py`

- `/assets/*` (Vite adds a content hash to every name): `public, max-age=31536000, immutable`.
- `index.html` (also the SPA fallback), the manifest and icons: `no-cache`, so a
  deploy is picked up on the next visit.
- `FileResponse` sends `ETag` and `Last-Modified` but does not answer
  `If-None-Match` with 304, so a revalidation re-downloads the small
  `index.html`. Fine at this size.
- Cloudflare caches by extension on its own; these headers make that safe
  because the hashed files never change and the HTML is always revalidated.

## Native client (for example iOS): what exists and what is missing

The REST API does not depend on the web UI, and personal access tokens already
work as `Authorization: Bearer` with no cookie or CSRF. A first native version
could ship with a token pasted into the app.

For a proper sign-in the OAuth server is the right base (authorization code,
PKCE S256, refresh rotation, public clients, `/oauth/revoke`), but as built it
**does not work for a native client**. Three gaps, none fixed yet:

1. **Audience.** Authorization requires `resource = <base>/mcp`, and OAuth
   access tokens are accepted only on `/mcp`; `/api` rejects them (deliberately,
   so an MCP token cannot be replayed against the REST API). A native app needs
   tokens bound to `<base>/api`. Smallest change: allow `resource=<base>/api` as
   a second audience at authorize and token time, and let `current_principal`
   accept OAuth tokens whose audience is `<base>/api` (MCP tokens stay refused
   there and the reverse). Scopes and refresh work unchanged.
2. **Redirect URIs.** Registration accepts `https` URIs and loopback only. An
   iOS app using `ASWebAuthenticationSession` can use an `https` universal-link
   callback (supported from iOS 17.4), which already passes. A custom scheme such
   as `darkroom://callback` is rejected; allow private-use schemes (RFC 8252)
   only if that is chosen, and keep the exact-match rule.
3. **Registration.** Dynamic registration is rate limited (20 a minute) and
   open. A native app can use it, or the client can be pre-registered by hand
   in `oauth_clients`.

## Smaller decisions

- **Versioning:** no `/api/v1` now. The API has one consumer. Introduce a prefix
  at the first breaking change rather than before.
- **Contract:** the OpenAPI schema is at `/api/openapi.json` behind sign-in; fetch
  it with a read-only token for client generation (for example
  swift-openapi-generator).
- **Token storage and revocation:** the app keeps tokens in the Keychain. PATs
  are listed and revoked at `/api/tokens` (browser session only); OAuth tokens
  are revoked at `/oauth/revoke`.
- **CORS:** not needed for a native client. Only `/oauth/register`, `/oauth/token`,
  `/oauth/revoke` and discovery answer cross-origin requests.

## Follow-ups (only when a native app is started)

- Allow the `<base>/api` audience (gap 1) with tests for both directions.
- Decide on custom-scheme redirects (gap 2).
- Add `/api/v1` only if a breaking change is planned.
