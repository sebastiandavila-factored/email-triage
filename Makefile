.DEFAULT_GOAL := help

.PHONY: help install dev test test-v test-unit test-e2e audit sbom lint format typecheck precommit check ttft eval eval-quick db-up db-down db-migrate db-revision db-shell frontend-install frontend-dev frontend-build

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (uv sync)
	uv sync

dev: ## Start development server
	@lsof -ti :8000 | xargs kill -9 2>/dev/null || true
	uv run fastapi dev

down: ## Kill process on port 8000
	@lsof -ti :8000 | xargs kill -9 2>/dev/null && echo "Port 8000 cleared" || echo "Port 8000 already free"

test: ## Run full test suite
	uv run pytest

test-v: ## Run tests with verbose output
	uv run pytest -v

test-unit: ## Run only unit tests (fast, no app/DB) — mirrors CI
	uv run pytest -m unit

test-e2e: ## Run only e2e tests (full app / real DB) — mirrors CI
	uv run pytest -m e2e

audit: ## Scan resolved deps for known vulnerabilities (pip-audit) — mirrors CI
	@uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt -o /tmp/req-audit.txt
	uvx pip-audit -r /tmp/req-audit.txt --strict

sbom: ## Generate a CycloneDX SBOM (sbom.json) from resolved prod deps
	@uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt -o /tmp/req-sbom.txt
	uvx --from cyclonedx-bom cyclonedx-py requirements /tmp/req-sbom.txt -o sbom.json
	@echo "Wrote sbom.json"

lint: ## Lint with ruff (auto-fix)
	uv run ruff check --fix

format: ## Format code with ruff
	uv run ruff format

typecheck: ## Type check with pyright
	uv run pyright

precommit: ## Run all pre-commit hooks
	uv run pre-commit run --all-files

ttft: ## Measure TTFT vs /triage (reads API_KEY from .env if not set). Usage: make ttft N=20
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python scripts/measure_ttft.py $(or $(N),10) $$API_KEY

check: lint format typecheck test ## Run lint + format + typecheck + tests

eval: ## Run full eval suite (classification + LLM judge). Reads GROQ_API_KEY from .env
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python -m evals.run_evals

eval-quick: ## Run eval — classification metrics only, no LLM judge (2x faster)
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python -m evals.run_evals --no-judge

eval-regression: ## Run the regression suite as a gate (exits non-zero below threshold)
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python -m evals.run_evals --suite regression --check

eval-capability: ## Run the capability suite (harder/ambiguous cases; trend-tracked)
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python -m evals.run_evals --suite capability

eval-passk: ## Run each case K times and report pass^k. Usage: make eval-passk K=5
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python -m evals.run_evals --no-judge --repeat $(or $(K),5)

db-up: ## Start local PostgreSQL via Docker Compose
	docker compose up -d db

db-down: ## Stop and remove local PostgreSQL container
	docker compose down

db-migrate: ## Apply all pending Alembic migrations
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run alembic upgrade head

db-revision: ## Generate a new Alembic migration (MSG=description required)
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run alembic revision --autogenerate -m "$(MSG)"

db-shell: ## Open psql shell against the local dev database
	docker compose exec db psql -U postgres email_triage

frontend-install: ## Install frontend npm dependencies
	npm --prefix frontend install

frontend-dev: ## Start frontend dev server on :5173 (backend must be on :8000)
	@lsof -ti :5173 | xargs kill -9 2>/dev/null || true
	npm --prefix frontend run dev

frontend-build: ## Build frontend for production (output: frontend/dist/)
	npm --prefix frontend run build
