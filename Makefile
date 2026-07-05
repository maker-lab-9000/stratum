# Stratum — developer entrypoints. One CI-runnable test command per side (T01).
.PHONY: install install-backend install-frontend \
        test test-backend test-frontend \
        dev-backend dev-frontend build-frontend clean \
        docker-build docker-up docker-down

install: install-backend install-frontend ## Install both sides

install-backend:
	cd backend && uv sync

install-frontend:
	cd frontend && npm install

## --- CI test entrypoints -------------------------------------------------
test: test-backend test-frontend ## Run the full suite (both sides)

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

## --- Dev servers ---------------------------------------------------------
dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

build-frontend:
	cd frontend && npm run build

## --- Docker (single-origin deployment, spec §9) --------------------------
docker-build:
	docker compose build

docker-up: ## Build + run the api (UI + API on :8000). Needs a .env (see .env.example).
	docker compose up -d --build

docker-down:
	docker compose down

## --- End-to-end release gate (T24) ---------------------------------------
e2e: ## Full docker-compose e2e: real api + fake LLM + controlled target
	docker compose -f docker-compose.e2e.yml up -d --build
	@echo "Waiting for api health…"
	@for i in $$(seq 1 40); do curl -fsS http://localhost:8000/api/health >/dev/null 2>&1 && echo "api healthy" && break; sleep 2; done
	@cd frontend && npm run test:e2e:stack; STATUS=$$?; cd ..; docker compose -f docker-compose.e2e.yml down -v; exit $$STATUS

clean:
	rm -rf backend/.venv backend/.pytest_cache frontend/node_modules frontend/dist
