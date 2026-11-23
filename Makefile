COMPOSE = docker compose --env-file .env -f ./deploy/compose.yml

format:
	uv run ruff check --fix && uv run ruff format

lint:
	uv run ruff check && uv run ruff format --check

test:
	uv run pytest

coverage:
	uv run pytest --cov --cov-report=term-missing

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

migrate:
	uv run alembic upgrade head

downgrade:
	uv run alembic downgrade -1

seed:
	uv run python -m scripts.seed

generate_migrations:
	uv run alembic revision --autogenerate -m "$(msg)"

.PHONY: format lint test coverage build clear run run_db run_dev down migrate downgrade seed generate_migrations
