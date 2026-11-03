.PHONY: up down test check shell telegram-poll bus-validar bus-formatear bus-revision bus-publicar
.PHONY: status logs tenant-health qr check-prod-config deploy backup-now restore-test
.PHONY: db-roles

check-prod-config:
	uv run python tools/check_prod_config.py

deploy:
	gh workflow run deploy.yml -f sha="$(SHA)"

backup-now:
	ssh deploy@$(HOST) /srv/autobot/deploy/backup.sh

restore-test:
	bash deploy/restore-test.sh

up:
	docker compose up -d --build

down:
	docker compose down

status:
	docker compose ps

# Creates fp_owner, fp_app and fp_readonly (or updates their passwords) without
# recreating the db container; needed after adding a role or rotating a password.
db-roles:
	docker compose exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh

logs:
	docker compose logs --tail=100 --follow $(SERVICE)

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

# Long polling of a tenant's own bot (SLUG=<slug>), e.g. to record Telegram
# fixtures. Needs the worker running (`make up`) and no webhook set on that bot.
# Local development of the demo bot's Telegram door uses a webhook through ngrok
# instead (see docs/runbooks/demo.md), the same mechanism as production.
telegram-poll:
	docker compose exec web python manage.py telegram_poll $(SLUG)

# Bus timetable tools: make bus-<tool> TENANT=<slug>. They run on the
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

# Legacy mirror sync until T08b; it does not publish the versioned runtime config.
tenant-sync:
	docker compose exec web python manage.py sync_tenants
	docker compose restart web worker

tenant-health:
	docker compose exec web python manage.py tenant_health $(SLUG)

# Public QR generated on the developer machine, without containers or secrets.
qr:
	PYTHONPATH=src uv run python -m tools.qr "$(SLUG)" $(ARGS)
