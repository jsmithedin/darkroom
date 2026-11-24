# Darkroom

Darkroom is a self-hosted film photography tracker with a REST API and a mobile-first React interface. It replaces the "Film Photography Tracker v2" Google Sheet. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the build plan.

Everything in the build plan is implemented except the manual checks listed in `docs/notes/mcp-client-checks.md` (OAuth with the real Claude clients) and installing the PWA on a phone. The MCP server at `/mcp` exposes read and write tools for rolls, stock, bulk film, reference data and stats, with every tool write recorded on the Activity page.

## Local development

Needs Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22+ (Vite 8 needs 20.19 or newer) and Docker (tests start Postgres 16 via testcontainers).

```
uv sync
uv run pytest
uv run ruff check . && uv run mypy backend/app

cd frontend && npm install && npm run dev     # Vite on :5173, proxies /api and /mcp to :8000
npm test && npm run typecheck             # frontend tests and types (run in frontend/)
```

Run the backend against a local Postgres:

```
docker run -d --name darkroom-pg -e POSTGRES_USER=darkroom -e POSTGRES_PASSWORD=darkroom \
  -e POSTGRES_DB=darkroom -p 5432:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://darkroom:darkroom@localhost:5432/darkroom
uv run alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend uv run uvicorn app.main:create_app --factory --reload
```

## Personal access tokens

For scripts and MCP clients. Create one while signed in (Settings screen in the app, or `POST /api/tokens` with `name`, `scopes` of `films:read` and/or `films:write`, optional `expires_at`). The token (`drk_...`) is shown once; only a hash is stored. Use it as `Authorization: Bearer drk_...` on `/api` and `/mcp`. `films:write` implies `films:read`. Revoke with `DELETE /api/tokens/{id}`; the list shows `last_used_at`. Tokens cannot create or revoke tokens; that needs a browser session.

## API documentation

Interactive docs are at `/api/docs` (and `/api/redoc`), and the OpenAPI schema at `/api/openapi.json`. They need sign-in: open them in the browser while signed in, or fetch the schema with `Authorization: Bearer drk_...` (a read token is enough).

`GET /api/stats?year=2026` returns monthly roll counts for the selected and preceding years, a year-to-date comparison and breakdowns. Omit the year to use the current year in the configured timezone. The API also serves `GET /api/stats/camera-idle` and `GET /api/stats/spend`. Cost per roll is annual film spend divided by the number of rolls developed that year.

## Connecting Claude (MCP)

The MCP server is `https://film.jamielab.uk/mcp` (your `PUBLIC_BASE_URL` plus `/mcp`). Tools: `list_rolls`, `get_stock`, `get_bulk_rolls`, `get_stats`, `get_dev_times`, `list_reference_data` (need `films:read`), and `log_roll`, `update_roll`, `record_purchase`, `record_bulk_load`, `record_given_away`, `record_stock_adjustment`, `create_bulk_roll`, `update_bulk_roll`, `add_reference_item` (need `films:write`). There are no delete tools. Films, cameras, developers and so on can be given by name or id, money is whole pence and lengths whole millimetres. Every successful write appears under **Activity** with the token or connector that made it.

**Claude Code, with a personal access token** (the route that has been verified):

```
claude mcp add --transport http darkroom https://film.jamielab.uk/mcp \
  --header "Authorization: Bearer drk_..."
```

**claude.ai custom connector, with OAuth:** Settings, Connectors, add a custom connector with the URL above and choose "Register automatically" (dynamic client registration). Sign in with Google, check the consent page lists the scopes, and approve. Claude's callback is `https://claude.ai/api/mcp/auth_callback`. You do not add it in Google Cloud; it is registered with Darkroom by the client itself. Darkroom does not support Claude's "published identity" (client ID metadata documents) option. OAuth with the real clients has not been run yet (see `docs/notes/mcp-client-checks.md`); use a personal access token if it gives trouble.

How OAuth works here: discovery is at `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource/mcp`, both built from `PUBLIC_BASE_URL`. Public clients register at `/oauth/register` (HTTPS or loopback redirect URIs, 20 registrations a minute). Authorization needs PKCE S256 and a Google sign-in from an allowed email. Access tokens last an hour, refresh tokens 30 days and rotate; replaying an old refresh token revokes the whole family. OAuth tokens only work on `/mcp`, never on `/api`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every PR and push to `main`: `backend` (ruff, mypy, pytest with a Postgres container), `frontend` (typecheck, tests and build) and `image` (Docker build, import smoke test, compose has no published ports). By convention `main` only receives PRs with all three passing (branch protection needs GitHub Pro on a private repo).

## Google sign-in setup

In Google Cloud Console create an OAuth client (type: Web application) and add these redirect URIs:

- `https://film.jamielab.uk/api/auth/callback` (the only redirect URI Google needs; it is for signing in to the web app and for the sign-in step of the Claude connector)
- `http://localhost:8000/api/auth/callback` for local development (with `PUBLIC_BASE_URL=http://localhost:8000`)

Put the client id and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and list the emails that may sign in in `ALLOWED_EMAILS` (JSON list). Anyone else sees a "not authorised" page and gets no session. Session cookies are `Secure`, so browsers only keep them over HTTPS (localhost is exempt in Chrome and Firefox).

## CSV export

Settings has an Export section with a download link per table (rolls, stock movements, bulk rolls, cameras, lenses, films, developers, filters, formats, dev time references and settings). The same files come from `GET /api/export/<table>.csv` with a session or a token that has `films:read`, for example `curl -H "Authorization: Bearer drk_..." https://film.jamielab.uk/api/export/rolls.csv -o rolls.csv`, and `GET /api/export` lists the names. The first row is the column names; ids are UUIDs, dates are ISO, money is whole pence and lengths whole millimetres, empty cells are blank. Text that starts with `=`, `+`, `-` or `@` gets a leading apostrophe so a spreadsheet does not run it as a formula. Sessions, tokens, OAuth tables and users are never exported.

## Importing the Google Sheet

One-off (safe to repeat) import of the old sheet. Export each tab as CSV (File, Download, CSV) into `./import/` (the folder is gitignored): `Tracker`, `Films`, `Lists`, `Bulk`, `Purchases` and `Dev Times`. Google's own names (`Film Photography Tracker v2 - Tracker.csv`) are fine.

Sign in to the app once first (the import needs a user), then:

```
docker compose run --rm -v "$PWD/import:/import:ro" app python -m app.importer.cli /import --dry-run
docker compose run --rm -v "$PWD/import:/import:ro" app python -m app.importer.cli /import
```

Locally, from the repository root: `PYTHONPATH=backend uv run python -m app.importer.cli ./import`. It prints what it inserted and a reconciliation (117 rolls; 60 in 2025, 57 in 2026; 61 x 35mm and 88 x 120 in stock; Bulk 1 7.3 m left). If any figure differs, or a camera, lens, film, developer, filter or format is unknown, **nothing is imported** and it exits non-zero (1 for a mismatch, 2 for bad input). `--dry-run` checks and rolls back. Re-running inserts nothing.

## Native clients

The REST API is independent of the web UI and accepts `Authorization: Bearer drk_...` tokens, so a native app can use a personal access token today. OAuth sign-in for a native app is not supported yet: OAuth tokens only work on `/mcp`. See `docs/notes/frontend-serving-and-native-client.md` for the gaps and the smallest fix.

## Deploy (Docker Compose)

```
cp .env.example .env        # fill in
docker compose build
docker compose up -d
```

Compose runs `app` (FastAPI serving the API, `/mcp` and the built frontend; migrations run on start), `db` (Postgres 16, named volume) and `backup` (nightly dumps, see below). No ports are published. `app` joins the existing external docker network named by `CLOUDFLARED_NETWORK`.

Cloudflare setup (tunnel route, the WAF skip rule that stops Claude's servers being blocked, and the optional Access policy) is in `docs/cloudflare.md`.

Tunnel: in the cloudflared config add an ingress rule `film.jamielab.uk` -> `http://app:8000` (use the container name `darkroom-app-1` if `app` is ambiguous on the shared network), then add the DNS route. Set `FORWARDED_ALLOW_IPS` to the tunnel network's subnet so `X-Forwarded-*` is trusted only from cloudflared.

## Backups and restore

The `backup` service runs `pg_dump -Fc` once at start-up and then every night at `BACKUP_HOUR` (UTC, default 02:00). Dumps are written to `./backups/darkroom-YYYYMMDD.dump` (gitignored, owned by root, readable by everyone on the host; a second dump on the same day gets a time in its name and nothing is overwritten). Dumps older than `BACKUP_RETENTION_DAYS` (default 14) are deleted, but the newest three are always kept, so a run of bad dumps cannot push out the last good ones. A dump is written to a temporary file and only moved into place after `pg_dump` succeeds and `pg_restore --list` can read it. Restarting the service does not take another dump if one from the last 12 hours exists. Check the last one with `ls -l backups/` or `docker compose logs backup`.

**Take a backup now:** `docker compose run --rm backup once`

**Restore into a scratch database** (to look at or compare, nothing live is touched):

```
docker compose run --rm backup /ops/restore.sh /backups/darkroom-20261123.dump scratch
```

It restores into a temporary database, then renames it to `scratch`, and prints the row counts of `rolls` and `stock_movements`; compare them with the live ones (`docker compose exec db psql -U darkroom -Atc "select count(*) from rolls"`). A failed restore changes nothing. It refuses a database that already exists unless you add `--replace`, which keeps the old one renamed `<name>_old_<time>`. Drop the scratch copy afterwards with `docker compose exec db psql -U darkroom -d postgres -c "DROP DATABASE scratch"`.

**Disaster recovery** (replace the live database from a dump):

```
docker compose stop app backup
docker compose run --rm backup /ops/restore.sh /backups/darkroom-20261123.dump darkroom --replace
docker compose start app backup
```

The previous database is kept as `darkroom_old_<time>`. Once the app looks right, drop it: `docker compose exec db psql -U darkroom -d postgres -c "DROP DATABASE darkroom_old_<time>"`. An empty database also produces valid nightly dumps, so check the app after any volume or database change.

Copy `./backups` off the NUC now and then (a dump on the same disk does not survive the disk). `ops/backup/selftest.sh` runs the whole backup and restore against a throwaway Postgres and compares counts; CI runs it.
