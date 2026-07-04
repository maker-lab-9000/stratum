# Stratum — developer entrypoints. One CI-runnable test command per side (T01).
.PHONY: install install-backend install-frontend \
        test test-backend test-frontend \
        dev-backend dev-frontend build-frontend clean

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

clean:
	rm -rf backend/.venv backend/.pytest_cache frontend/node_modules frontend/dist
