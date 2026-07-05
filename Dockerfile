# syntax=docker/dockerfile:1
# Stratum — single-origin image: the api serves the built frontend, runs the
# pipeline (Playwright warm + TCP traceroute), and hosts the SQLite/Postgres
# store. Deployment target: amd64 (spec §9); build with `--platform linux/amd64`
# on other hosts.

# --- Stage 1: build the frontend static bundle -------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: the api (backend + pipeline + static) --------------------------
FROM python:3.12-slim AS api
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/backend/.venv/bin:$PATH"

# Traceroute tooling: mtr (preferred by the collector) + tcptraceroute fallback.
RUN apt-get update && apt-get install -y --no-install-recommends \
      mtr-tiny tcptraceroute ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv for dependency management (pinned binary from the official image).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app/backend

# Install Python deps first so the layer caches across source changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# Chromium + its OS deps for the Playwright warm step; version matches the
# playwright package just installed, so no revision drift.
RUN playwright install --with-deps chromium

# Application source + the built frontend the api serves single-origin.
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Defaults keep the SQLite file and downloaded GeoLite2 DBs on the mounted volume.
ENV DATABASE_URL="sqlite:////app/backend/data/stratum.db" \
    MAXMIND_DB_DIR="/app/backend/data/geoip"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
