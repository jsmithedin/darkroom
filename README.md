# Darkroom

Self-hosted film photography tracker: REST API, mobile-first React PWA and an authenticated MCP server, replacing the "Film Photography Tracker v2" Google Sheet. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the build plan.

Status: Phase 1 in progress. Google sign-in, sessions, CSRF and personal access tokens and the sign-in and token screens work; data screens are still to come.

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

For scripts and MCP clients. Create one while signed in (Settings screen in the app, or `POST /api/tokens` with `name`, `scopes` of `films:read` and/or `films:write`, optional `expires_at`). The token (`drk_...`) is shown once; only a hash is stored. Use it as `Authorization: Bearer drk_...` on `/api` (and `/mcp` from Phase 6). `films:write` implies `films:read`. Revoke with `DELETE /api/tokens/{id}`; the list shows `last_used_at`. Tokens cannot create or revoke tokens; that needs a browser session.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every PR and push to `main`: `backend` (ruff, mypy, pytest with a Postgres container), `frontend` (typecheck, tests and build) and `image` (Docker build, import smoke test, compose has no published ports). By convention `main` only receives PRs with all three passing (branch protection needs GitHub Pro on a private repo).

## Google sign-in setup

In Google Cloud Console create an OAuth client (type: Web application) and add these redirect URIs:

- `https://film.jamielab.uk/api/auth/callback`
- `http://localhost:8000/api/auth/callback` for local development (with `PUBLIC_BASE_URL=http://localhost:8000`)

Put the client id and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and list the emails that may sign in in `ALLOWED_EMAILS` (JSON list). Anyone else sees a "not authorised" page and gets no session. Session cookies are `Secure`, so browsers only keep them over HTTPS (localhost is exempt in Chrome and Firefox).

## Deploy (Docker Compose)

```
cp .env.example .env        # fill in
docker compose build
docker compose up -d
```

Compose runs `app` (FastAPI serving the API, `/mcp` and the built frontend; migrations run on start) and `db` (Postgres 16, named volume). No ports are published. `app` joins the existing external docker network named by `CLOUDFLARED_NETWORK`.

Tunnel: in the cloudflared config add an ingress rule `film.jamielab.uk` -> `http://app:8000` (use the container name `darkroom-app-1` if `app` is ambiguous on the shared network), then add the DNS route. Set `FORWARDED_ALLOW_IPS` to the tunnel network's subnet so `X-Forwarded-*` is trusted only from cloudflared.
