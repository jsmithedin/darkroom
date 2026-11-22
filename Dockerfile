# syntax=docker/dockerfile:1

# --- Build the frontend
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Python runtime serving the API, MCP and the built frontend
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./backend/
COPY --from=frontend /frontend/dist ./frontend/dist
ENV PYTHONPATH=/srv/backend FRONTEND_DIST=/srv/frontend/dist
RUN useradd --system --uid 1000 darkroom
USER darkroom
EXPOSE 8000
CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
