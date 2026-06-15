.DEFAULT_GOAL := help

.PHONY: help install dev test test-v lint format typecheck precommit check ttft eval eval-quick db-up db-down db-migrate db-revision db-shell frontend-install frontend-dev frontend-build

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
