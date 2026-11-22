# Darkroom

Self-hosted film photography tracker: REST API, mobile-first React PWA and an authenticated MCP server, replacing the "Film Photography Tracker v2" Google Sheet. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the build plan.

Status: Phase 1 in progress. Google sign-in, sessions and CSRF work; tokens and data screens are still to come.

## Local development

Needs Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22+ (Vite 8 needs 20.19 or newer) and Docker (tests start Postgres 16 via testcontainers).

```
uv sync
uv run pytest
uv run ruff check . && uv run mypy backend/app

cd frontend && npm install && npm run dev     # Vite on :5173, proxies /api and /mcp to :8000
```

Run the backend against a local Postgres:

```
docker run -d --name darkroom-pg -e POSTGRES_USER=darkroom -e POSTGRES_PASSWORD=darkroom \
  -e POSTGRES_DB=darkroom -p 5432:5432 postgres:16
export DATABASE_URL=postgresql+asyncpg://darkroom:darkroom@localhost:5432/darkroom
uv run alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend uv run uvicorn app.main:create_app --factory --reload
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every PR and push to `main`: `backend` (ruff, mypy, pytest with a Postgres container), `frontend` (typecheck and build) and `image` (Docker build, import smoke test, compose has no published ports). By convention `main` only receives PRs with all three passing (branch protection needs GitHub Pro on a private repo).

## Automatic deploys (self-hosted runner on the NUC)

`.github/workflows/deploy.yml` deploys `main` after CI passes on a push to `main`. It runs on a GitHub Actions runner installed on the NUC, which only makes outbound connections to GitHub, so nothing extra is exposed. It never runs for pull requests.

Each deploy: checks out the exact commit CI tested, runs `docker compose up -d --build` with the NUC's env file, waits for `/api/health` inside the container (up to 60 s), then checks the public URL. Migrations run when the container starts. A failure prints the app logs and fails the run.

### One-off setup on the NUC

1. Create a user for the runner and put it in the `docker` group (it can then control Docker, so treat it as privileged):
   ```
   sudo useradd -m -s /bin/bash -G docker gh-runner
   ```
2. Move the real env file somewhere outside any checkout that the runner user can read, and lock it down:
   ```
   sudo install -d -o gh-runner -g gh-runner -m 700 /opt/darkroom
   sudo cp /path/to/current/.env /opt/darkroom/.env
   sudo chown gh-runner:gh-runner /opt/darkroom/.env && sudo chmod 600 /opt/darkroom/.env
   ```
3. Install the runner as that user. In GitHub: repo, Settings, Actions, Runners, New self-hosted runner (Linux x64). Follow the download and `./config.sh` commands it shows, adding the label `nuc` (`./config.sh --url ... --token ... --labels nuc`). Then install it as a service:
   ```
   sudo ./svc.sh install gh-runner && sudo ./svc.sh start
   ```
4. Set repo variables (Settings, Secrets and variables, Actions, Variables):
   - `DEPLOY_ENV_FILE` = `/opt/darkroom/.env`
   - `DEPLOY_HEALTH_URL` = `https://film.jamielab.uk/api/health`
5. The compose project name is pinned to `darkroom` so the existing database volume (`darkroom_dbdata`) is reused. If your current stack has a different project name, change `COMPOSE_PROJECT_NAME` in the workflow to match, or the deploy will start a fresh, empty database. Stop the old manually-started stack first (`docker compose down`, without `-v`) so the two do not fight over container names.

Keep the repo private and do not enable "run workflows from fork pull requests" for it. Restrict the runner to this repository.

### Rolling back

Revert the bad commit through a PR and merge it; the deploy runs again. In an emergency, on the NUC: check out the previous good commit in any clone and run `COMPOSE_PROJECT_NAME=darkroom docker compose --env-file /opt/darkroom/.env up -d --build`. Migrations are not reversed automatically, so a rollback across a migration needs `alembic downgrade` by hand.

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
