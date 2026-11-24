# Cloudflare notes

Cloudflare is the tunnel only. The app has its own sign-in (Google, allowlisted
emails), so Cloudflare Access is not enabled.

## Tunnel route

Add an ingress rule to the cloudflared config and a DNS route:

```
- hostname: film.jamielab.uk
  service: http://app:8000
```

Use the container name (`darkroom-app-1`) if `app` is ambiguous on the shared
network. Compose publishes no ports; `app` only joins the network named by
`CLOUDFLARED_NETWORK`. Set `FORWARDED_ALLOW_IPS` to that network's subnet so
uvicorn trusts `X-Forwarded-*` only from cloudflared. All external URLs (OAuth
issuer, redirects, metadata) come from `PUBLIC_BASE_URL`, never from request
headers.

## WAF skip rule

Claude's servers call `/mcp`, `/oauth/*` and `/.well-known/*` directly. Bot
Fight mode and managed challenges can block them, which shows up as a connector
that cannot connect or sign in. Add a custom rule (Security, WAF, Custom rules)
with action **Skip**, skipping Bot Fight Mode, Super Bot Fight Mode and the
managed rules, for:

```
(http.host eq "film.jamielab.uk" and (
  starts_with(http.request.uri.path, "/mcp") or
  starts_with(http.request.uri.path, "/oauth/") or
  starts_with(http.request.uri.path, "/.well-known/")))
```

Those paths are protected by the app: `/mcp` returns 401 without a valid token,
`/oauth/register` is rate limited, and the rest only issue tokens after a
Google sign-in and consent. Note `/oauth/token` has no rate limit of its own;
codes are single use, last 60 seconds and are bound to a PKCE verifier.

## Caching

CSV exports and OAuth responses send `Cache-Control: no-store` or
`private, no-store`. Cloudflare caches `.csv` paths by default, so do not add a
cache rule that overrides the origin's headers.

## Optional: Cloudflare Access (not enabled)

An Access policy could sit in front of the web UI paths (everything except
`/mcp`, `/oauth/*` and `/.well-known/*`, which must stay reachable). The
trade-off is a second login on every device and rules to maintain, for a
modest gain, because the app already requires an allowlisted Google account.
If you turn it on, test the connector and `claude mcp add` afterwards.
