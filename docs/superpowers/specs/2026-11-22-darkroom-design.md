# Darkroom: film photography tracker, design spec

Date: 2026-11-22. Status: draft for review.

A self-hosted web app that replaces the "Film Photography Tracker v2" Google Sheet. It runs on an Intel NUC (Arch Linux, Docker Compose, existing cloudflared) at `film.jamielab.uk`. People sign in with Google. AI clients (claude.ai, Claude Code) reach the same data through an authenticated MCP server at `/mcp`. Single user for now. Most entry happens on a phone, often with wet hands.

Keep it small. It is a personal tool: no multi-tenancy, queues, Redis or microservices.

## 1. Decisions

| # | Decision |
|---|---|
| 1 | New repo `~/git/darkroom`. (`~/git/film-tracker` is an unrelated AWS project and is untouched.) |
| 2 | Opening balances come from the sheet's Films tab, Opening 35mm / Opening 120, as `opening` movements dated 2026-11-22 (Films!N1). All imported rolls have `counts_against_stock = false`. |
| 3 | Each bulk load stores a snapshot of its metres, computed with the settings at the time. The figure is an estimate. There is no recalculate action. |
| 4 | Formats are an editable reference table, seeded with 35mm, 120 and 110. |
| 5 | EI allows decimals: `numeric(7,2)`, displayed without trailing zeros. |
| 6 | Single user. No roles, no per-user data. `users` plus `created_by`/`updated_by` stay for attribution. A second allowlisted user would share the same data. |
| 7 | Stock can never go negative. Every write that could cause it is checked under a per-film/format lock. |
| 8 | No Cloudflare Access. Cloudflare is the tunnel only; the app does its own auth. |
| 9 | Timezone defaults to Europe/London (a setting). Timestamps are UTC in the database. |
| 10 | No delete tools in MCP. Deletes are UI-only. Scopes are `films:read` and `films:write`. |
| 11 | `counts_against_stock` is a general per-roll toggle, default on, editable. |
| 12 | Bulk bought date, cost and supplier are optional. Bulk 1 imports unpriced. |
| 13 | No 110 stock. Zero-count openings are skipped. |
| 14 | MCP writes are recorded in an `audit_events` table with a read-only UI screen. |

## 2. Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.x (typed, async, asyncpg), Alembic, Pydantic v2. uv, ruff, mypy (strict-ish), pytest against a real Postgres (testcontainers). No SQLite.
- Database: PostgreSQL 16+ in the same compose project, named volume, not published.
- Frontend: React + TypeScript + Vite, TanStack Query. No component library. Charts: Chart.js, tree-shaken, because it does the monthly bars plus cumulative line and theming in one small package. Breakdowns are plain CSS bars.
- MCP: official `mcp` Python SDK (current release 2.3.0, class `MCPServer`), streamable HTTP, mounted in the FastAPI app. Pin `mcp>=2.3,<3`; the SDK docs say 3.0 changes `TokenVerifier`/`AuthSettings` defaults.
- Deploy: one app image (FastAPI serves the built frontend, `/api`, `/mcp`) plus Postgres plus a backup sidecar. Compose services join the existing cloudflared network. No published ports.

## 3. Domain and data model

All tables have `id uuid pk`, `created_at`, `updated_at`, `created_by`, `updated_by` (FKs to `users`) unless stated. Money is integer pence. Lengths are integer millimetres. No floats for either.

### Reference tables
- `users`: `email` (citext unique), `name`, `google_sub` (unique), `is_active`. Upserted on first allowed login. The allowlist lives in config.
- `settings` (single row): `leader_mm` (250), `frame_pitch_mm` (38), `timezone` ("Europe/London"). `CHECK > 0`.
- `formats`, `cameras`, `lenses`, `developers`, `filters`: `name` (unique), `archived_at`. `cameras` also has `fixed_lens bool` and `notes`.
- `films`: `name` (unique), `type` (`bw|colour|slide`), `box_iso int > 0`, `archived_at`.

Archived items stay valid on old rows and are hidden from dropdowns. Reference items are never deleted.

### rolls
`dev_date date`, `camera_id`, `lens_id` (null = N/A), `format_id`, `film_id`, `ei numeric(7,2) > 0`, `developer_id`, `dev_time_min numeric(5,2)` (null), `filter_id` (null), `subject`, `notes`, `source` (`factory|bulk`), `counts_against_stock bool default true`.
Indexes: `dev_date`, `(film_id, ei, developer_id)`, `(camera_id, dev_date)`.

Derived, never stored: year, month, film type, box ISO, stops vs box = log2(EI / box ISO), shown as +2, -1.

### stock_movements
Common: `film_id`, `format_id`, `kind` (`purchase|bulk_load|given_away|adjustment|opening`), `occurred_on`, `rolls int <> 0` (signed), `notes`.
- purchase: `rolls > 0`, `cost_pence` (receipt total), `supplier`.
- bulk_load: `rolls > 0` (cassettes), `bulk_roll_id`, `exposures_per_cassette`, `metres_mm` (snapshot: `rolls * (leader_mm + exposures * frame_pitch_mm)`). Format must be 35mm.
- given_away: `rolls < 0`.
- adjustment: `counted_to` (the entered figure, kept for audit). `rolls` holds the delta computed at entry time.
- opening: `rolls >= 0`.

CHECK constraints per kind: fields belonging to other kinds must be null; required fields must be present.

### bulk_rolls
`label` (unique), `film_id`, `length_mm > 0`, `cost_pence` (null), `supplier` (null), `bought_on` (null), `used_before_mm default 0`, `finished bool`, `notes`.

Derived:
- `cassettes_loaded = sum(rolls)` of its loads.
- `used_mm = used_before_mm + sum(metres_mm)`.
- `left_mm = length_mm - used_mm`.
- `exposures_left = max(0, floor((left_mm - leader_mm) / frame_pitch_mm))`.
- `cost_per_36_pence = cost_pence / (length_mm / (leader_mm + 36 * frame_pitch_mm))`, rounded to the penny, null when unpriced. Uses current settings.

Check against the sheet: Bulk 1, 17 000 mm, 9 700 used before tracking, 7 300 left, `floor((7300 - 250) / 38) = 185` exposures.

### dev_time_refs
`film_id`, `ei`, `developer_id`, `minutes`, `notes`; unique on `(film_id, ei, developer_id)`.

### Other tables
- `audit_events` (immutable): `at`, `actor_kind` (`pat|oauth`), `token_id` or `client_id`, `user_id`, `tool`, `entity_type`, `entity_id`, `summary jsonb`.
- `import_ledger`: `tab`, `fingerprint`, `occurrence`, `entity_type`, `entity_id`; unique on `(tab, fingerprint, occurrence)`.
- Auth tables: see section 6.

### Stock rule
`in_stock(film, format) = sum(movements.rolls) - count(rolls where counts_against_stock and same film/format)`, exposed as a SQL view.

**Why a per-row flag for imported history:** the sheet used a cutoff date, which breaks when you backfill or edit old rolls. A per-row flag is explicit, visible and editable. The import sets it false for every roll dated on or before 2026-11-22; new rolls default true.

### Non-negative stock (decision 7)
The service layer takes `pg_advisory_xact_lock` on each affected `(film, format)` pair (in sorted order when two are touched), recomputes stock inside the transaction and rejects the write if any pair would be below zero. Covered writes:
- Create or edit a roll (film, format or flag changes).
- Create `given_away`.
- Edit or delete any movement a roll depends on.
- Flipping `counts_against_stock` on.

Rolls with the flag off are exempt. The error is plain, e.g. "No Kodak Gold 120 in stock. Record a purchase or a recount first." The UI error offers a "Record a recount" shortcut. Adjustments set stock to a counted figure `>= 0`.

## 4. Backend structure

One service layer (`services/`) owns every derived figure and every invariant (stock, stops, bulk maths, stats, non-negative check). REST routes and MCP tools are thin adapters over it, so MCP can never do more than the UI. All pure maths (stops, bulk) sits in plain functions with table-driven tests.

## 5. API surface

REST under `/api`, Pydantic v2 schemas. Cookie auth requires CSRF; Bearer auth does not.

- Session: `GET /me`, `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`.
- Reference data (`cameras|lenses|developers|filters|films|formats`): `GET` (`include_archived`), `POST`, `PATCH /{id}`, `POST /{id}/archive|unarchive`.
- Rolls: `GET /rolls` (filters: `from`, `to`, `film`, `camera`, `developer`, `source`, `q`, pagination), `POST`, `GET|PATCH|DELETE /rolls/{id}`, `GET /cameras/{id}/last-roll` (lens and format prefill).
- Stock: `GET /stock`, `GET|POST /stock-movements` (one body shape per kind), `PATCH|DELETE /stock-movements/{id}`, `POST /stock-adjustments` (counted figure in, delta computed server-side).
- Bulk: `GET|POST /bulk-rolls`, `GET|PATCH|DELETE /bulk-rolls/{id}` (with derived fields).
- Dev times: `GET /dev-times` (grouped by film + EI + developer, newest first), CRUD `/dev-time-refs`.
- Stats: `GET /stats?year=`, `GET /stats/camera-idle`, `GET /stats/spend`.
- Settings: `GET|PATCH /settings`.
- Tokens: `GET|POST /tokens`, `DELETE /tokens/{id}`.
- Audit: `GET /audit-events` (read-only).
- Ops: `GET /health` (checks DB), `GET /export/{table}.csv` for every table.

### Stats definitions
For a selected year (default current) against the previous year: rolls per month with a cumulative line (current year stops at the current month, London time); rolls so far against last year to the same date; breakdowns by camera, film, developer, format, type and source; per-camera last-use date, oldest first; spend per year (purchases by `occurred_on`, plus bulk rolls by `bought_on`, unpriced or undated bulk excluded) and cost per roll.

## 6. MCP tools

Typed with Pydantic models; descriptions written for an LLM. Every write runs through the same service layer and is recorded in `audit_events`.

- Read (`films:read`): `list_rolls` (date range, film, camera, developer, source, text search), `get_stock`, `get_bulk_rolls`, `get_stats` (year), `get_dev_times` (film, EI, developer), `list_reference_data`.
- Write (`films:write`): `log_roll`, `update_roll`, `record_purchase`, `record_bulk_load`, `record_given_away`, `record_stock_adjustment`, `create_bulk_roll`, `update_bulk_roll`, `add_reference_item`.
- No delete tools.
- `films:write` implies `films:read` (the spec requires scope hierarchies to be accounted for).
- A blocked stock write returns a clear tool error naming the missing purchase or recount.

## 7. Auth

### Browser login (Google OIDC)
- Authlib client, authorization code flow with PKCE, `state` and `nonce`. Requires `email_verified`.
- Email checked against `ALLOWED_EMAILS` after the callback. Others see a clear "not authorised" page and get no session.
- Server-side sessions in Postgres. The cookie holds an opaque random id (hash stored), `Secure; HttpOnly; SameSite=Lax`, 30-day sliding lifetime with an absolute cap.
- CSRF: per-session token in `X-CSRF-Token` on unsafe methods, plus an Origin check.

### MCP authorization
Target: the MCP authorization spec at `modelcontextprotocol.io/specification/latest` (the dated 2026-07-28 revision; the fetched page carried no version label, so this is inferred from its links and example headers). I will re-confirm the revision at the start of Phase 6.

From that spec:
- The MCP server MUST implement RFC 9728 protected resource metadata. 401 responses carry `WWW-Authenticate: Bearer resource_metadata=...`. Insufficient scope returns 403 with `error="insufficient_scope"` and the needed scopes.
- The authorization server MUST provide RFC 8414 or OIDC discovery metadata. Tokens MUST be audience-validated (RFC 8707 `resource`). Access tokens are never accepted in the query string. No token passthrough.
- Client registration: Client ID Metadata Documents SHOULD be supported; Dynamic Client Registration is MAY and marked deprecated. Claude's connector documentation still describes DCR ("register automatically"), so **DCR is in scope**. CIMD is deferred until needed.
- Authorization responses include `iss` (RFC 9207) and the metadata sets `authorization_response_iss_parameter_supported`.

SDK reality (from the Python SDK docs): the SDK is a resource server only. It verifies tokens through a `TokenVerifier` and publishes the protected-resource metadata; its in-SDK authorization server (`auth_server_provider=`) is documented as legacy. So **the app implements the authorization server itself** in FastAPI: `/oauth/authorize`, `/oauth/token`, `/oauth/register`, `/oauth/revoke`, plus `/.well-known/oauth-authorization-server`. Authlib has no Starlette authorization-server integration, so these endpoints are hand-written. The surface is small (authorization_code and refresh_token grants) and test-heavy.

Design:
- `authorize` requires a session; if absent it runs the Google login and allowlist above, then shows a consent page listing client name, redirect URI and requested scopes.
- PKCE S256 required. Exact `redirect_uri` match. Pre-registered redirect for Claude: `https://claude.ai/api/mcp/auth_callback`, and `https://claude.com/api/mcp/auth_callback` (documented as a possible future move). Claude Code's redirect handling (likely loopback URIs via DCR) is unverified; see section 14.
- Access tokens last 1 hour. Refresh tokens rotate with reuse detection. All stored hashed.
- A single `TokenVerifier` backs `/mcp` and `/api` Bearer auth: it accepts OAuth access tokens and personal access tokens, and returns `(user, scopes)`.
- Tables: `sessions`, `oauth_clients`, `oauth_codes`, `oauth_tokens` (hashed access/refresh, scopes, client, user, expiry, rotation family), `personal_access_tokens`.

### Personal access tokens
Created in the UI with a name, scopes and an expiry. Format `drk_<random>`, shown once; only a SHA-256 hash and a short prefix are stored. Shown with `last_used_at`; revocable. Work as `Authorization: Bearer` on `/api` and `/mcp`.

### Mounting
`mcp.streamable_http_app()` is mounted at the root with `Mount("/")`, after our own routes. The host app's lifespan must enter `mcp.session_manager.run()`. The SDK's default DNS-rebinding protection allows only localhost Host headers, so configure `TransportSecuritySettings(allowed_hosts=["film.jamielab.uk", "film.jamielab.uk:*"], allowed_origins=["https://film.jamielab.uk"])`. Custom MCP routes are unauthenticated by default, so none are used. These SDK behaviours come from the docs and must be verified by a spike in Phase 0 (mount, lifespan, Host check, well-known route location).

## 8. Cloudflare and proxying

- Cloudflare is the tunnel only. No Cloudflare Access (decision 8).
- uvicorn runs with `--proxy-headers` and `--forwarded-allow-ips` limited to the tunnel network, so `X-Forwarded-*` is trusted only from the tunnel.
- All external URLs (OAuth redirect URIs, metadata, issuer) come from `PUBLIC_BASE_URL`, never from request headers.
- Public paths: `/`, `/auth/*`, `/oauth/*`, `/.well-known/*`. Everything under `/api` and `/mcp` returns 401 without a valid credential and reveals nothing else. `/oauth/token` and `/oauth/register` are rate limited.
- A Cloudflare WAF skip rule for `/mcp`, `/oauth/*` and `/.well-known/*` stops Bot Fight mode blocking Claude's servers.
- The README documents an optional Cloudflare Access policy for the web UI paths that leaves `/mcp`, `/oauth/*` and `/.well-known/*` reachable. Trade-off: a second login on every device and rules to maintain, for a modest gain, because the app already has allowlisted Google auth. Not enabled.

## 9. Frontend (mobile first)

- Log screen: remembers last camera, lens, format and developer. Picking a camera fills lens and format from its most recent roll. Picking a film sets EI to its box ISO; stops vs box updates live. After saving, setup fields are kept and subject, notes and dev time cleared. Recent rolls list below. The "Counts against stock" toggle sits below the fold on the roll form.
- Purchases screen with three modes: Bought, Loaded from bulk (shows metres and exposures left on the chosen spool) and Given away.
- Stock view grouped by type, zero rows hidden by default, with a meter per bulk spool. Negative cannot occur, so no red state.
- Edit and delete for rolls and movements, with a confirm dialog on delete.
- Reference list screens: simple add, edit, archive.
- Dev times view; dashboard; Settings (tokens, bulk maths, timezone); audit events list.
- Light and dark themes follow the system. Touch targets at least 44px, 16px inputs. PWA manifest and icons.

## 10. Migration from the sheet

An idempotent import command reads CSV exports of Tracker, Films, Purchases, Bulk, Lists and Dev Times from `./import`.

- Dates are dd/mm/yyyy. Blank cells become null. Format "120" or "35mm" is normalised against the formats table.
- Tracker columns B, C, H, I, K (Year, Month, Type, Box ISO, Stops vs box) are ignored and recalculated.
- Lists creates cameras, lenses, formats, developers and filters. Films creates films, plus `opening` movements for Opening 35mm and Opening 120 dated 2026-11-22; zero counts are skipped.
- Tracker rows become rolls. Rolls dated on or before 2026-11-22 get `counts_against_stock = false`. A camera, lens, film or developer missing from the reference lists aborts the run with the full list of unknown names; nothing is auto-created.
- Bulk becomes `bulk_rolls` (Bulk 1: Fomapan 100, 17 000 mm, 9 700 mm used before tracking; date, cost, supplier null).
- Purchases (empty today, still supported): negative rolls become `given_away`; a bulk roll id makes `bulk_load`; otherwise `purchase`.
- Dev Times: the hand-typed reference block becomes `dev_time_refs`. The logged-times block is derived and ignored.
- Idempotency: each row gets a fingerprint (tab, content hash, occurrence number) recorded in `import_ledger`, so identical rows (several rolls on 19/04/2026) are kept and a second run inserts nothing. The run is a single transaction.
- Reconciliation printed after import, and the run fails if any figure differs from the expected sheet totals:
  - total rolls: 117
  - rolls per year: 2025: 60; 2026: 57 (as of 2026-11-22)
  - stock: 61 x 35mm and 88 x 120 at the opening date
  - metres left on Bulk 1: 7.3

## 11. Operations

- `GET /api/health` checks the database connection (for Uptime Kuma).
- Nightly `pg_dump` (custom format) in a small sidecar to a mounted backup folder, 14 days retention, with a documented and tested restore command.
- CSV export of every table.
- Secrets (Google client id and secret, session key, token signing key, DB password) come from env or Docker secrets, never committed. `.env.example` provided.
- Settings (leader, frame pitch, timezone) are stored in the database and editable in the UI.
- README covers: local dev, Google Cloud OAuth client setup (redirect URIs for web login and MCP), CSV export, the import, the Docker build, compose services, adding the connector in claude.ai and Claude Code, backups and restore.

## 12. Testing

- pytest with a real Postgres. Table-driven tests for the stock and bulk maths: negative movements, partial cassettes, adjustments, the non-negative rule under concurrent writes.
- Auth tests: allowlist refusal, scope enforcement on every write tool, token revocation, expiry, refresh rotation and reuse detection, audience validation, PKCE failures.
- Import tests: idempotency (run twice), unknown-name abort, reconciliation figures.
- Frontend: component tests for the log form behaviours (prefill, EI default, live stops).

## 13. Build phases

| Phase | Scope | Testable at the end |
|---|---|---|
| 0 Skeleton | uv, ruff, mypy, pytest + testcontainers, Alembic, Vite app, multi-stage Dockerfile, compose (cloudflared network, no ports), `/api/health`, MCP mount spike | `docker compose up` serves a page at film.jamielab.uk with correct scheme/host; tests green; spike confirms the mount, lifespan and Host-check behaviour |
| 1 Auth (browser and PAT) | Google OIDC, allowlist, sessions, CSRF, token UI and API, audit columns | Allowed email signs in, other email refused; bad CSRF rejected; revoked PAT gives 401 |
| 2 Reference data and rolls | Reference CRUD with archive, rolls CRUD, derived fields, log screen, recent list | Log a roll on the phone; archived camera hidden from dropdowns but valid on old rolls |
| 3 Stock and bulk | Movements, constraints, non-negative rule, stock view, bulk maths and meters, settings, purchases screen | Stock arithmetic and bulk metres match hand-worked cases; concurrent writes cannot go negative |
| 4 Sheet import | Import command, ledger, reconciliation | Reconciliation matches section 10; second run inserts nothing |
| 5 Dev times and stats | Grouped dev times, manual refs, stats, dashboard | Totals and year-to-date comparison match the sheet |
| 6 MCP and OAuth | Authorization server, consent screen, DCR, `/mcp` tools, scope enforcement, `audit_events` | `claude mcp add` works with a PAT; claude.ai custom connector completes OAuth and calls `get_stock` |
| 7 Operations and polish | Backups and restore, CSV export, PWA, themes, touch pass, README | Restore tested; installs to home screen; usable one-handed |

If OAuth proves painful with a client, PATs in Claude Code are the fallback and claude.ai can wait.

## 14. Items to verify during build

- The exact dated MCP revision at the start of Phase 6 (the fetched page showed no version label).
- SDK mounting behaviour (Phase 0 spike): `Mount("/")` placement, lifespan, Host/Origin checks, well-known route location, FastAPI versus plain Starlette.
- Whether claude.ai and Claude Code use DCR, CIMD or fixed redirect URIs in practice (Phase 6).
