# =============================================================================
# Makefile — Likida AI Enterprise
#
# Usage:  make <target>
#
# Requires: Python 3.11+ in .venv/, Docker, docker compose v2
# =============================================================================

SHELL        := /bin/bash
PROJECT      := b2b_ai
PYTHON       := .venv/bin/python
PIP          := .venv/bin/pip
PYTEST       := $(PYTHON) -m pytest
RUFF         := $(PYTHON) -m ruff
MYPY         := $(PYTHON) -m mypy
BUILD        := $(PYTHON) -m build

DOCKER_IMAGE := b2b-ai
DOCKER_TAG   := latest

# ---------- Default target ---------------------------------------------------

.DEFAULT_GOAL := help

# ---------- Help --------------------------------------------------------------

.PHONY: help
help: ## Show this help
	@echo "Usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------- Setup & Install ---------------------------------------------------

.PHONY: install
install: ## Create venv & install deps (editable mode + test extras)
	python3 -m venv .venv
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -e ".[test]"
	$(PIP) install ruff mypy build
	@echo "✔  install done"

# ---------- Quality -----------------------------------------------------------

.PHONY: lint
lint: ## Lint with ruff (check only, no auto-fix)
	$(RUFF) check .

.PHONY: format
format: ## Format with ruff (auto-fix)
	$(RUFF) format .

.PHONY: typecheck
typecheck: ## Run mypy static analysis
	$(MYPY) $(PROJECT)

# ---------- Tests -------------------------------------------------------------

.PHONY: test
test: ## Run test suite (pytest, quiet)
	$(PYTEST) -q

.PHONY: test-verbose
test-verbose: ## Run test suite verbose (pytest -v -s)
	$(PYTEST) -v -s

.PHONY: test-security
test-security: ## Run tests with Bandit security checks
	$(PYTEST) -v -k "security or bandit" --tb=short

.PHONY: coverage
coverage: ## Run tests with coverage report
	$(PYTEST) --cov=$(PROJECT) --cov-report=term-missing --cov-report=html --cov-fail-under=80
	@echo "✔  HTML report → htmlcov/index.html"

# ---------- Build ------------------------------------------------------------

.PHONY: build
build: ## Build sdist + wheel into dist/
	rm -rf dist/ build/
	$(BUILD)
	@echo "✔  dist/ contents:"
	@ls -lh dist/

# ---------- Docker -----------------------------------------------------------

.PHONY: docker-build
docker-build: ## Build Docker image
	docker compose build --no-cache

.PHONY: docker-up
docker-up: ## Start services (foreground: docker compose up)
	docker compose up --build

.PHONY: docker-down
docker-down: ## Stop and remove containers
	docker compose down -v

.PHONY: docker-down-prod
docker-down-prod: ## Stop production stack
	-docker compose -f docker-compose.prod.yml down -v

# ---------- Database ---------------------------------------------------------

.PHONY: migrate
migrate: ## Run Alembic migrations (head)
	$(PYTHON) -m alembic upgrade head

.PHONY: migrate-new
migrate-new: ## Create a new Alembic migration (NAME required)
	@test -n "$(NAME)" || (echo "Usage: make migrate-new NAME=add_users_table"; exit 1)
	$(PYTHON) -m alembic revision --autogenerate -m "$(NAME)"

.PHONY: seed
seed: ## Seed demo data (XML fixtures into DB)
	$(PYTHON) -c "from b2b_ai.db.db import Database; db = Database(); db.migrate(); print('✔  DB migrated & seeded')"

# ---------- Deploy -----------------------------------------------------------

.PHONY: deploy
deploy: ## Run production deploy script (local Docker Compose on VPS)
	bash ./deploy.sh local

.PHONY: deploy-cloud
deploy-cloud: ## Run cloud deploy (Vercel + Railway)
	bash ./deploy.sh cloud

# ---------- Cleanup -----------------------------------------------------------

.PHONY: clean
clean: ## Remove build artifacts, caches, coverage, eggs
	rm -rf dist/ build/ *.egg-info .pytest_cache htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✔  cleaned"
