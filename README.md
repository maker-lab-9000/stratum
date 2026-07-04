# Stratum — Cache & Delivery Analyzer

Self-hosted tool: give it a URL, and it collects **deterministic evidence** (DNS,
N-request header samples, TCP traceroute, ASN/geo), has an **LLM interpret** that
evidence into a cache verdict + findings, and renders a monitoring-style report.

The hard architectural rule: deterministic code collects ground-truth evidence
verbatim and never interprets it; the LLM produces the entire verdict and every
claim cites evidence that the backend machine-checks for existence. See the
requirements spec for the full contract.

> **Status:** early build. This is the T01 scaffold — health endpoint + wired
> test/build tooling on both sides. Features land task-by-task (T02…T24).

## Stack

- **Backend:** Python 3.12 · FastAPI · SQLAlchemy · pytest (managed with [uv](https://docs.astral.sh/uv/))
- **Frontend:** React · Vite · TypeScript · Tailwind v4 · Vitest
- **Deploy:** Docker Compose (amd64 homelab target). Traceroute needs the
  `NET_RAW` capability — wired in T21.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (backend deps + Python 3.12, auto-installed by uv)
- Node.js 20+ and npm (frontend)
- `make` (optional convenience wrapper)

## Quick start

```bash
# Install both sides
make install            # or: (cd backend && uv sync) && (cd frontend && npm install)

# Run the tests (CI entrypoint)
make test               # backend pytest + frontend vitest

# Run the dev servers (two terminals)
make dev-backend        # FastAPI on http://localhost:8000
make dev-frontend       # Vite on http://localhost:5173 (proxies /api → :8000)
```

Health check:

```bash
curl http://localhost:8000/api/health   # -> {"status":"ok"}
```

## Layout

```
backend/     FastAPI app + pipeline + tests (uv project)
frontend/    Vite + React + TS + Tailwind + vitest
docker-compose.yml   deployment stub (fleshed out in T21)
Makefile     install / test / dev entrypoints
```

## Testing

| Command             | Runs                                  |
|---------------------|---------------------------------------|
| `make test`         | full suite, both sides                |
| `make test-backend` | `uv run pytest` in `backend/`         |
| `make test-frontend`| `npm test` (vitest) in `frontend/`    |

No live network or live-LLM calls run by default — fakes/fixtures only. Live
tests are marked `@pytest.mark.live` and excluded from the default run.

## Configuration

Secrets come from the environment only, never the DB or API responses. The full
env var matrix (LLM keys, MaxMind, vantage label, auth) is documented alongside
the Docker deployment in T21. A `.env.example` ships then.
