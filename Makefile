.PHONY: up down test check shell telegram-poll

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

# Long polling of the development test bot, or of a tenant's own bot with SLUG=<slug>
# (design.md §6.4). Needs the worker running (`make up`) and TEST_BOT_TOKEN in .env.
telegram-poll:
	docker compose exec web python manage.py telegram_poll $(SLUG)
