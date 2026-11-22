COMPOSE = docker compose --env-file .env -f ./deploy/compose.yml

format:
	uv run ruff check --fix && uv run ruff format

lint:
	uv run ruff check && uv run ruff format --check

test:
	uv run pytest

build:
	$(COMPOSE) down --rmi all && \
	docker builder prune -f && \
	$(COMPOSE) up --build

clear:
	$(COMPOSE) down --rmi all && \
	docker builder prune -f

run:
	$(COMPOSE) up

run_db:
	$(COMPOSE) up -d db pgweb

run_dev:
	uv run uvicorn app.main:app --reload

down:
	$(COMPOSE) down

.PHONY: format lint test build clear run run_db run_dev down
