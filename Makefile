.PHONY: install test build run stop lint typecheck clean migrate ingest rescore reset-db

# Local development
install:
	uv sync --all-extras
	uv run playwright install chromium
	cp -n .env.example .env 2>/dev/null || true

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check . --fix

typecheck:
	uv run mypy src/

migrate:
	uv run alembic upgrade head

run:
	uv run uvicorn gyn_kol.main:app --reload

ingest:
	uv run python -c "import asyncio; from gyn_kol.flows.ingestion_flow import ingestion_flow; asyncio.run(ingestion_flow())"

rescore:
	uv run python -c "import asyncio; from gyn_kol.flows.rescore_flow import rescore_flow; asyncio.run(rescore_flow())"

reset-db:
	-pkill -f 'uvicorn gyn_kol.main:app' 2>/dev/null
	rm -f gyn_kol.db
	uv run alembic upgrade head

stop:
	-pkill -f 'uvicorn gyn_kol.main:app' 2>/dev/null
	-docker compose -f docker/compose.yml down 2>/dev/null

# Docker
build:
	docker compose -f docker/compose.yml build

up:
	docker compose -f docker/compose.yml up -d

down:
	docker compose -f docker/compose.yml down

logs:
	docker compose -f docker/compose.yml logs -f app

clean:
	docker compose -f docker/compose.yml down -v
