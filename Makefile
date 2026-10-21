.PHONY: up down test check shell

up:
	docker compose up -d --build

down:
	docker compose down

test:
	uv run pytest

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	PYTHONPATH=src uv run lint-imports
	uv run pytest

shell:
	docker compose exec web python manage.py shell
