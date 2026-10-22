.PHONY: up down test check shell telegram-poll bus-validar bus-formatear bus-revision bus-publicar

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

# Bus timetable tools (design.md §10.1): make bus-<tool> TENANT=<slug>. They run on the
# developer machine against tenants/<slug>/datasets/timetable/.
BUS_TOOL = PYTHONPATH=src uv run python -m tools

bus-validar:
	$(BUS_TOOL).bus_validar $(TENANT)

bus-formatear:
	$(BUS_TOOL).bus_formatear $(TENANT)

# Writes revision/<slug>/horarios.html and .pdf with the changes since the last
# datos/<slug>/* tag. ARGS="--solo-html" skips the PDF; ARGS="--desde <ref>" picks the base.
bus-revision:
	$(BUS_TOOL).bus_revision $(TENANT) $(ARGS)

# Tags HEAD as datos/<slug>/<today>, after commit and deploy. It does not push the tag.
bus-publicar:
	$(BUS_TOOL).bus_publicar $(TENANT)
