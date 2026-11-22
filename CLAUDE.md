# Darkroom

Self-hosted film photography tracker (replaces a Google Sheet). FastAPI + Postgres backend, React PWA frontend, authenticated MCP server at `/mcp`. Single user.

- Spec: `docs/superpowers/specs/2026-11-22-darkroom-design.md` (decisions, data model, auth)
- Plan: `docs/superpowers/plans/2026-11-22-darkroom.md` (task by task; each task is a GitHub issue)
- Findings from spikes: `docs/notes/`

## Commands

```
uv sync                                  # install
uv run pytest                            # tests (needs Docker: testcontainers starts Postgres 16)
uv run ruff check . && uv run ruff format --check .
uv run mypy backend/app
uv run alembic -c backend/alembic.ini upgrade head   # needs DATABASE_URL
uv run alembic -c backend/alembic.ini revision --autogenerate -m "msg"
```

## Dependencies

Anything imported by `backend/app` belongs in `dependencies`, not the `dev` group: tests install dev deps and will not catch a miss, but the Docker image (`uv sync --no-dev`) will crash on start. After adding imports, check with `docker build -t darkroom-check . && docker run --rm -e PYTHONPATH=/srv/backend darkroom-check python -c "import app.main"`.

## Layout

- `backend/app/` FastAPI app (`main.py` has `create_app(settings)`), `config.py` Settings, `db.py` engine and `get_session`
- `backend/tests/` pytest; `conftest.py` provides `db_session` (rolled back per test) and `client` fixtures
- `backend/alembic/` async migrations; `env.py` reads `Settings().database_url` unless the ini sets `sqlalchemy.url` (tests do). `models/__init__.py` must import every model so autogenerate sees it. `test_models_match_migrations` fails if models and migrations drift.
- `models/base.py`: `Base` (naming convention) and `AuditMixin` (id, timestamps, created_by/updated_by). Every table uses the mixin unless the spec says otherwise.
- `backend/app/mcp/server.py`: `build_mcp()` and Host/Origin settings derived from `PUBLIC_BASE_URL`. `create_app` mounts the MCP app at `/` **last** and enters `mcp.session_manager.run()` in its lifespan (FastAPI won't run the mount's lifespan). See `docs/notes/mcp-mount-spike.md` before touching this.
- `backend/app/spa.py`: `RootApp` is the final catch-all mount. `/mcp` and `/.well-known` go to the MCP app; unknown `/api/*` is a JSON 404; other GETs serve `frontend/dist` with SPA fallback. New top-level public paths (`/auth`, `/oauth`) must be real FastAPI routes added before the mount.
- `frontend/`: Vite + React + TS + TanStack Query. **Vite 8 needs Node >= 20.19**; nvm's default here is 20.11, so use `/usr/bin/node` (v26) or `.nvmrc` (22). Commands: `npm run dev|build|typecheck`.
- `Dockerfile` (frontend build, then python:3.12-slim runtime; runs `alembic upgrade head` then uvicorn with `--proxy-headers`), `compose.yaml` (`app`, `db`, no `ports:`, external network from `CLOUDFLARED_NETWORK`), `.env.example`. Check with `docker compose --env-file .env.example config` and `docker compose build`.
- Auth (Task 1.1): `auth/principal.py` (`Principal`, `current_principal` dependency; write implies read), `auth/sessions.py` (Postgres sessions, cookie `darkroom_session` holds a random id, only its SHA-256 is stored; 30-day sliding, 90-day cap), `auth/csrf.py`, `auth/google.py` (Authlib + joserfc OIDC with PKCE/state/nonce behind the `OIDCProvider` protocol), `api/auth.py` (`/api/auth/login|callback|logout`, `/api/me`). **Protect every new endpoint with `Depends(current_principal)`**: it enforces CSRF (Origin + `X-CSRF-Token`) for cookie-authenticated unsafe methods. The browser gets its CSRF token from `GET /api/me`.
- The model is `UserSession` (table `sessions`). Login-in-progress state (state/nonce/verifier) is a short-lived signed cookie `darkroom_oidc`, not a DB row.
- Tests: `migrated_db` (session fixture) applies migrations once; `client` truncates `users` CASCADE first. Auth tests replace `app.state.oidc` with a fake (`tests/auth/conftest.py`). Tests that downgrade must upgrade again.
- Tests that hit `/mcp` need `LifespanManager` (see `test_mcp_mount.py`).
- Tests run on one session-scoped event loop (see `pyproject.toml`)

## Conventions

- Money is integer pence, lengths integer millimetres. No floats for either.
- No SQLite, ever. Tests use real Postgres.
- One service layer (`services/`) owns derived figures and invariants; REST and MCP are thin adapters.
- External URLs come from `PUBLIC_BASE_URL`, never request headers.
- Work follows the plan's steps (TDD), one commit per task with the message given in the issue.

## Workflow (GitHub issues and PRs)

- Every plan task is a GitHub issue (`gh issue list`, `gh issue view N`). Work from the issue: follow its steps in order.
- One branch and one PR per task (or per tightly related group), branched from an up-to-date `main`, named like `task-1.1-google-login`. Never push to `main` directly.
- Keep issues current as you go: tick completed steps in the issue body, comment on findings, deviations from the plan, or blockers, and comment with the commit/PR when done.
- PR body links the issue with `Closes #N` (use `Refs #N` if a manual step remains, and leave the issue open until it is verified). Issues close when the PR merges.
- If the work changes how things run or are laid out, update this file, the README and `docs/notes/` in the same PR.
- Run `uv run pytest`, ruff and mypy (plus `npm run typecheck` for frontend work) before opening the PR.
- CI (`.github/workflows/ci.yml`) runs three jobs on every PR and push to `main`: `backend` (ruff, format check, mypy, pytest), `frontend` (typecheck, build) and `image` (docker build, import `app.main`, compose has no `ports:`). `main` is protected: changes land by PR with all three green. If CI fails, fix it before asking for a merge; do not bypass the protection.

