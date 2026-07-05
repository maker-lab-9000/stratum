# Stratum — Cache & Delivery Analyzer

Self-hosted tool: give it a URL, and it collects **deterministic evidence** (DNS,
N-request header samples, TCP traceroute, ASN/geo), has an **LLM interpret** that
evidence into a cache verdict + findings, and renders a monitoring-style report.

The hard architectural rule: deterministic code collects ground-truth evidence
verbatim and never interprets it; the LLM produces the entire verdict and every
claim cites evidence that the backend machine-checks for existence. See the
requirements spec for the full contract.

> **Status:** active build. The full launch → live-run → report → history flow
> works end-to-end, and a single-origin Docker image ships the whole app.
> Remaining polish lands task-by-task (security gate, a11y pass, e2e suite).

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

## Deploy with Docker (single origin)

The `Dockerfile` builds the frontend and bakes it into the api image, so one
container serves the UI, the REST/SSE API, and the pipeline. Target host is
**amd64** (Proxmox / Docker homelab).

```bash
cp .env.example .env          # fill in LLM key(s), MAXMIND_LICENSE_KEY, VANTAGE_LABEL
docker compose up -d --build  # UI + API on http://localhost:8000
curl http://localhost:8000/api/health   # -> {"status":"ok"}
```

Data (SQLite DB + downloaded GeoLite2 databases) persists on the `stratum-data`
volume, so history survives `docker compose restart`.

> **⚠ Traceroute needs raw-socket privileges.** The compose file grants the api
> `NET_RAW` + `NET_ADMIN` (`cap_add`). Without them the app still runs and
> analyses still complete — the traceroute stage records a typed error and the
> report renders with an empty route — but you get no hop/geo data. On hosts
> that forbid `cap_add`, use host networking instead.

Building on a non-amd64 machine? `docker compose build` with
`platforms: ["linux/amd64"]` uncommented in `docker-compose.yml`, or
`docker build --platform linux/amd64 -t stratum-api .`.

**Optional Postgres** instead of SQLite:

```bash
# in .env: DATABASE_URL=postgresql+psycopg://stratum:stratum@db:5432/stratum
docker compose --profile postgres up -d --build
```

**No LLM keys?** The app still boots and serves the UI; the launch view shows an
empty model list and reports render in the degraded (verdict-unavailable) state.

## Layout

```
backend/     FastAPI app + pipeline + tests (uv project)
frontend/    Vite + React + TS + Tailwind + vitest
Dockerfile   single-origin image (frontend build + api)
docker-compose.yml   api (+ optional Postgres), volume, capabilities
.env.example live-config template (copy to .env)
Makefile     install / test / dev / docker entrypoints
```

## Testing

| Command             | Runs                                  |
|---------------------|---------------------------------------|
| `make test`         | full suite, both sides                |
| `make test-backend` | `uv run pytest` in `backend/`         |
| `make test-frontend`| `npm test` (vitest) in `frontend/`    |
| `npm run test:e2e`  | Playwright a11y/visual/keyboard (in `frontend/`) |
| `make e2e`          | Full docker-compose release gate (below) |

**Release gate — `make e2e`.** Brings up a real stack (`docker-compose.e2e.yml`):
the api with a keyless **`fake` LLM** (`LLM_PROVIDER=fake`, deterministic recorded
verdicts; a URL containing `__degrade__` forces the degraded path) plus a
controlled **target site** with configurable cache headers. Playwright drives
full flows against the live api — happy path (launch → live run → report serving
layer + progression → history), degraded path, and sampler→UI progression
integrity — then tears the stack down. A restart mid-run never leaves a report
stuck `running` (interrupted jobs are reconciled to `error` on boot).

Accessibility & visual are covered by Playwright + axe-core (`frontend/e2e/`):
no serious/critical axe violations on all four views, `prefers-reduced-motion`
kills animations, keyboard-only launch + report open, and layout holds at
1280/390 with no page horizontal scroll. Palette contrast is enforced
deterministically by `frontend/src/components/contrast.test.ts`.

No live network or live-LLM calls run by default — fakes/fixtures only. Live
tests are marked `@pytest.mark.live` and excluded from the default run.

## Configuration

Secrets come from the environment only — never the DB, API responses, or logs.
Copy `.env.example` to `.env` and fill in what you need (all optional except a
provider key, which the verdict requires):

| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic provider (verdict) |
| `OPENROUTER_API_KEY` | OpenRouter provider (verdict) |
| `MAXMIND_LICENSE_KEY` | Download GeoLite2 ASN/City on boot; unset → ASN/geo `unknown` |
| `MAXMIND_DB_DIR` | Where the `.mmdb` files live (default under the data volume) |
| `VANTAGE_LABEL` | Disclosed on every report's map (where the runner sits) |
| `DEFAULT_REQUEST_COUNT` / `DEFAULT_INTERVAL_MS` | Sampling defaults |
| `DATABASE_URL` | SQLite path (default) or a Postgres DSN |
| `PIPELINE_CONCURRENCY` / `LOG_LEVEL` | Pipeline workers / log verbosity |
| `AUTH_ENABLED` / `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` | Optional access gate (see T22) |

`GET /api/models` returns model ids for the configured providers — never keys.

> **Do not expose Stratum publicly without the auth gate.** It makes outbound
> requests to operator-supplied URLs and is built for trusted LAN / homelab use.

## Security (§10)

All controls are env-driven and **off by default** (trusted-LAN posture). Each
checklist line maps to a control and a test:

| §10 requirement | Control | Test |
|---|---|---|
| Optional auth gate | `AUTH_ENABLED` + `BASIC_AUTH_USER/PASS` → HTTP Basic on every route (health exempt) | `test_security::test_auth_gate_blocks_without_credentials` |
| Optional outbound allowlist | `OUTBOUND_ALLOWLIST` host patterns; off-list targets 400 at POST | `test_security::test_allowlist_rejects_offlist_target_at_post` |
| Private-range targets | Allowed by default (LAN tool) and disclosed via the route, never silently public | `test_security::test_private_target_detection` |
| No secret reflection | Analysed-site headers/HTML stored verbatim, rendered as React text nodes (never `eval`/`dangerouslySetInnerHTML`) | `test_security::test_malicious_headers_are_stored_raw`, `Section02.test::malicious header values … render as text` |
| Secrets from env only | LLM keys read from env; absent from DB rows, API responses, logs; `GET /api/models` returns ids only | `test_security::test_llm_key_never_appears_in_responses_or_db` |
| Vantage disclosed | Every report payload carries `vantage` | `test_security::test_every_report_payload_discloses_vantage` |
