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

## Layout

- `backend/app/` FastAPI app (`main.py` has `create_app(settings)`), `config.py` Settings, `db.py` engine and `get_session`
- `backend/tests/` pytest; `conftest.py` provides `db_session` (rolled back per test) and `client` fixtures
- `backend/alembic/` async migrations; `env.py` reads `Settings().database_url` unless the ini sets `sqlalchemy.url` (tests do). `models/__init__.py` must import every model so autogenerate sees it. `test_models_match_migrations` fails if models and migrations drift.
- `models/base.py`: `Base` (naming convention) and `AuditMixin` (id, timestamps, created_by/updated_by). Every table uses the mixin unless the spec says otherwise.
- Tests run on one session-scoped event loop (see `pyproject.toml`)

## Conventions

- Money is integer pence, lengths integer millimetres. No floats for either.
- No SQLite, ever. Tests use real Postgres.
- One service layer (`services/`) owns derived figures and invariants; REST and MCP are thin adapters.
- External URLs come from `PUBLIC_BASE_URL`, never request headers.
- Work follows the plan's steps (TDD), one commit per task with the message given in the issue.
