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
- `frontend/`: Vite + React + TS + TanStack Query. **Vite 8 needs Node >= 20.19**; nvm's default here is 20.11, so use `/usr/bin/node` (v26) or `.nvmrc` (22). Commands: `npm run dev|build|typecheck|test` (Vitest + Testing Library, jsdom).
- Frontend auth (Task 1.3): `src/api/client.ts` `apiFetch<T>` is the only way to call the API: it sends the cookie, adds `X-CSRF-Token` on unsafe methods (fetched from `/api/me` and cached) and sends 401s to `/login`. Hooks in `src/api/hooks.ts` (`useMe`, `useTokens`, `useCreateToken`, `useRevokeToken`, `useLogout`). Routes in `src/App.tsx` (react-router); `AppShell` guards everything but `/login`. Tests mock `fetch` with `vi.stubGlobal` and call `setCsrfToken`/`setUnauthorizedHandler` to avoid real redirects. Styles are plain CSS in `src/styles/global.css` (44px touch targets, 16px inputs, light/dark by system).
- `Dockerfile` (frontend build, then python:3.12-slim runtime; runs `alembic upgrade head` then uvicorn with `--proxy-headers`), `compose.yaml` (`app`, `db`, no `ports:`, external network from `CLOUDFLARED_NETWORK`), `.env.example`. Check with `docker compose --env-file .env.example config` and `docker compose build`.
- Auth (Task 1.1): `auth/principal.py` (`Principal`, `current_principal` dependency; write implies read), `auth/sessions.py` (Postgres sessions, cookie `darkroom_session` holds a random id, only its SHA-256 is stored; 30-day sliding, 90-day cap), `auth/csrf.py`, `auth/google.py` (Authlib + joserfc OIDC with PKCE/state/nonce behind the `OIDCProvider` protocol), `api/auth.py` (`/api/auth/login|callback|logout`, `/api/me`). **Protect every new endpoint with `Depends(current_principal)`**: it enforces CSRF (Origin + `X-CSRF-Token`) for cookie-authenticated unsafe methods. The browser gets its CSRF token from `GET /api/me`.
- Tokens (Task 1.2): `Principal` lives in `auth/identity.py` (re-exported from `auth/principal.py`). `current_principal` accepts `Authorization: Bearer drk_...` (no CSRF) or the session cookie; a bad Bearer never falls back to the cookie. **Use `Depends(require_scope(READ|WRITE))` on data endpoints** (write implies read; sessions hold both). Token management (`/api/tokens`) uses `require_session_principal`, so a token cannot mint or revoke tokens. PATs: `drk_` + random, only SHA-256 and an 8-char prefix stored, revoke sets `revoked_at` (rows kept), `last_used_at` updated on every use. `auth/verifier.py::verify_bearer` is where OAuth access tokens join in Phase 6. Test helpers: `scoped` fixture adds `/api/_test/read|write`, `make_token` creates a PAT via the API.
- Reference data (Task 2.1): `models/reference.py` (`NamedItem` abstract base: case-insensitive `citext` unique `name`, `archived_at`; `Format, Camera, Lens, Developer, Filter, Film`, `AppSettings` single-row `settings` table, `RefKind`). `services/reference.py` (`list_items/create_item/update_item/archive_item/unarchive_item`; raises `NotFoundError`/`DuplicateNameError`, which the API maps to 404/409). `api/reference.py` registers the same five routes per kind from a `Spec` list, so adding a field means editing `schemas/reference.py` and the model only. Reads need `films:read`, writes `films:write`. Items are archived, never deleted. Migration 0004 seeds formats 35mm/120/110 and the settings row. PATCH treats null as "unchanged" for non-nullable columns; `exclude_unset` decides which fields are touched.
- Test fixtures: `authed` (signed-in session client with CSRF/Origin headers preset) and `bearer_client(*scopes)` (cookie-less client holding a fresh PAT), both in `tests/support.py`.
- The model is `UserSession` (table `sessions`). Login-in-progress state (state/nonce/verifier) is a short-lived signed cookie `darkroom_oidc`, not a DB row.
- Tests: `migrated_db` (session fixture) applies migrations once; `client` calls `reset_db` first (truncates every table except `users`, `formats`, `settings`; deletes users; removes non-seed formats; resets settings), so **seed data survives between tests and must never be truncated with CASCADE through `users`**. Add new seeded tables to `KEEP_TABLES`. Auth tests replace `app.state.oidc` with a fake (`tests/auth/conftest.py`). Tests that downgrade must upgrade again.
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
- CI (`.github/workflows/ci.yml`) runs three jobs on every PR and push to `main`: `backend` (ruff, format check, mypy, pytest), `frontend` (typecheck, tests, build) and `image` (docker build, import `app.main`, compose has no `ports:`). GitHub branch protection is unavailable (private repo, free plan), so this is by convention: never push to `main`, and only merge a PR once all three jobs are green. Any deploy workflow must itself wait for CI.

