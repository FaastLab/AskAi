# =============================================================================
# AskAi — developer commands
# Requires: uv (https://docs.astral.sh/uv/), docker, docker compose
# =============================================================================

.DEFAULT_GOAL := help

PYTHON := uv run python
UV := uv

# ---------- Help ----------
.PHONY: help
help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- Environment ----------
.PHONY: install
install:  ## Install all workspace dependencies via uv
	$(UV) sync --all-packages --dev

.PHONY: env
env:  ## Copy .env.example to .env if missing
	@test -f .env || cp .env.example .env && echo ".env ready"

# ---------- Infrastructure ----------
.PHONY: up
up: env  ## Start postgres, redis, minio (infra only)
	docker compose up -d

.PHONY: up-app
up-app: env  ## Build + start full stack as background services (api + worker + web)
	docker compose --profile app up -d --build
	@set -a && [ -f .env ] && . ./.env; set +a; \
	  echo "API:  http://localhost:$${API_PORT:-8000}"; \
	  echo "Web:  http://localhost:$${WEB_PORT:-3000}"; \
	  echo "Docs: http://localhost:$${API_PORT:-8000}/docs"

.PHONY: down-app
down-app:  ## Stop the application containers (keeps infra up)
	docker compose --profile app down

.PHONY: ps
ps:  ## Show AskAi containers
	docker compose --profile app ps

.PHONY: down
down:  ## Stop all containers
	docker compose down

.PHONY: nuke
nuke:  ## Stop containers and DELETE all data volumes (destructive)
	docker compose down -v

.PHONY: logs
logs:  ## Tail container logs
	docker compose logs -f

# ---------- Database ----------
.PHONY: migrate
migrate:  ## Apply Alembic migrations
	cd packages/core && $(UV) run alembic upgrade head

.PHONY: migrate-new
migrate-new:  ## Generate a new migration: make migrate-new MSG="add foo"
	cd packages/core && $(UV) run alembic revision --autogenerate -m "$(MSG)"

.PHONY: migrate-down
migrate-down:  ## Roll back one migration
	cd packages/core && $(UV) run alembic downgrade -1

# ---------- Quality gates ----------
.PHONY: lint
lint:  ## Run ruff lint
	$(UV) run ruff check packages

.PHONY: fmt
fmt:  ## Format with ruff
	$(UV) run ruff format packages
	$(UV) run ruff check --fix packages

.PHONY: typecheck
typecheck:  ## Run mypy --strict
	$(UV) run mypy packages

.PHONY: test
test:  ## Run pytest with coverage
	$(UV) run pytest --cov=packages --cov-report=term-missing

.PHONY: test-fast
test-fast:  ## Run pytest without coverage
	$(UV) run pytest -x

.PHONY: check
check: lint typecheck test  ## Run lint + typecheck + test

# ---------- Dev loop ----------
.PHONY: dev
dev: up migrate  ## Start infra and run API + worker (foreground)
	@set -a && [ -f .env ] && . ./.env; set +a; \
	  echo "Starting AskAi dev stack..."; \
	  echo "  API:    http://localhost:$${API_PORT:-8000}"; \
	  echo "  Docs:   http://localhost:$${API_PORT:-8000}/docs"; \
	  echo "  UI:     http://localhost:3000  (run 'make ui' separately)"; \
	  echo "  MinIO:  http://localhost:9001"; \
	  $(UV) run uvicorn faastlab_askai_api.main:app --reload --host 0.0.0.0 --port $${API_PORT:-8000}

.PHONY: worker
worker:  ## Run Celery worker (in a second terminal)
	$(UV) run celery -A faastlab_askai_indexing.celery_app:celery_app worker --loglevel=info

.PHONY: ingest
ingest:  ## Ingest local files: make ingest TENANT=demo-public SOURCE=./corpus/uk_finreg/_downloads
	$(UV) run python -m faastlab_askai_indexing.cli --tenant $(TENANT) --path $(SOURCE)

.PHONY: search
search:  ## Search: make search TENANT=demo-public QUERY="capital requirements" [K=5]
	$(UV) run python -m faastlab_askai_search.cli --tenant $(TENANT) --query "$(QUERY)" --k $${K:-5}

.PHONY: search-json
search-json:  ## Search but always prints JSON: make search-json TENANT=… QUERY="…" [K=5]
	$(UV) run python -m faastlab_askai_search.cli --tenant $(TENANT) --query "$(QUERY)" --k $${K:-5} --json

.PHONY: ask
ask:  ## Ask AI: make ask TENANT=demo-public QUERY="..." [SESSION=uuid] [INCLUDE_SUPERSEDED=1]
	$(UV) run python -m faastlab_askai_askai.cli --tenant $(TENANT) --query "$(QUERY)" \
	  $${SESSION:+--session $$SESSION} $${INCLUDE_SUPERSEDED:+--include-superseded}

.PHONY: summarise
summarise:  ## Summarise tenant docs: make summarise TENANT=demo-public [DOCUMENT=uuid] [FORCE=1]
	$(UV) run python -m faastlab_askai_summarisation.cli --tenant $(TENANT) \
	  $${DOCUMENT:+--document $$DOCUMENT} $${FORCE:+--force}

.PHONY: mcp
mcp:  ## Run the MCP server over stdio: make mcp TENANT=demo-public
	ASKAI_TENANT=$(TENANT) $(UV) run python -m faastlab_askai_mcp.server

.PHONY: validate
validate:  ## Validate a report: make validate TENANT=… REPORT=./report.pdf
	$(UV) run python -m faastlab_askai_validators.cli --tenant $(TENANT) --report $(REPORT)

# ---------- Reranker fine-tuning (MSc track) ----------
.PHONY: rerank-triplets
rerank-triplets:  ## Generate triplets: make rerank-triplets TENANT=demo-public [SAMPLE=500]
	$(UV) run python -m faastlab_askai_search.training.triplets \
	  --tenant $(TENANT) --sample-size $${SAMPLE:-500} \
	  --output $${OUT:-training/triplets.jsonl}

.PHONY: rerank-train
rerank-train:  ## Fine-tune cross-encoder: make rerank-train [OUT=training/finreg-reranker-v1]
	$(UV) run python -m faastlab_askai_search.training.train \
	  --triplets $${TRIPLETS:-training/triplets.jsonl} \
	  --output-dir $${OUT:-training/finreg-reranker-v1} \
	  --epochs $${EPOCHS:-3}

.PHONY: rerank-eval
rerank-eval:  ## Compare rerankers: make rerank-eval TENANT=demo-public [RERANKERS="none bge ..."]
	$(UV) run python -m faastlab_askai_search.training.evaluate \
	  --tenant $(TENANT) \
	  --queries $${QUERIES:-training/eval_queries.jsonl} \
	  --rerankers $${RERANKERS:-none bge}

.PHONY: ui
ui:  ## Run the Vite + React chat UI on :3000 (in a third terminal)
	cd apps/web && npm install && npm run dev

# ---------- Demo ----------
.PHONY: demo-corpus
demo-corpus:  ## Ingest the UK FinReg demo corpus into demo-public tenant
	$(UV) run python -m corpus.uk_finreg.loader $${NO_SUMMARISE:+--no-summarise}

.PHONY: ingest-handbooks
ingest-handbooks:  ## Bulk-ingest regulator handbooks listed in handbook_sources.yaml
	$(UV) run python -m corpus.uk_finreg.handbook_ingester \
	  $${REGULATOR:+--regulator $$REGULATOR} \
	  $${DRY_RUN:+--dry-run} \
	  $${FORCE:+--force}

.PHONY: smoke
smoke:  ## End-to-end smoke tests (set SMOKE_BASE_URL, SMOKE_OPENAI_KEY before running)
	$(UV) run pytest tests/smoke -v --tb=short

.PHONY: ingest-handbooks-dry
ingest-handbooks-dry:  ## Print what would be ingested (no fetches, no embeddings)
	$(UV) run python -m corpus.uk_finreg.handbook_ingester --dry-run

# ---------- Watcher (regulator change feed) ----------
.PHONY: watcher-poll
watcher-poll:  ## One-shot poll of regulator feeds: make watcher-poll [REGULATOR=fca]
	$(UV) run python -m faastlab_askai_watcher poll $${REGULATOR:+--regulator $$REGULATOR}

.PHONY: watcher-feeds
watcher-feeds:  ## List configured feed URLs
	$(UV) run python -m faastlab_askai_watcher list-feeds

# ---------- Cleanup ----------
.PHONY: clean
clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	rm -rf .coverage htmlcov dist build
