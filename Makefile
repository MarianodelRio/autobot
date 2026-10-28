.PHONY: up down test check shell telegram-poll bus-validar bus-formatear bus-revision bus-publicar
.PHONY: status logs tenant-health qr check-prod-config deploy backup-now restore-test admin-tunnel
.PHONY: demo-up demo-down

check-prod-config:
	uv run python tools/check_prod_config.py

deploy:
	gh workflow run deploy.yml -f sha="$(SHA)"

backup-now:
	ssh deploy@$(HOST) /srv/autobot/deploy/backup.sh

restore-test:
	bash deploy/restore-test.sh

admin-tunnel:
	ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18000:127.0.0.1:8000 deploy@$(HOST)

up:
	docker compose up -d --build

down:
	docker compose down

status:
	docker compose ps

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

# Long polling of the development demo bot, or of a tenant's own bot with SLUG=<slug>.
# Needs the worker running (`make up`) and DEMO_TELEGRAM_TOKEN in .env.
telegram-poll:
	docker compose exec web python manage.py telegram_poll $(SLUG)

# Keeps the demo bot's Telegram door polling in the background (needs DEMO_TELEGRAM_*
# in .env). demo-down only stops the poller, not the rest of the stack.
demo-up:
	docker compose --profile demo up -d

demo-down:
	docker compose --profile demo stop demo-poller

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

tenant-health:
	docker compose exec web python manage.py tenant_health $(SLUG)

# Public QR generated on the developer machine, without containers or secrets.
qr:
	PYTHONPATH=src uv run python -m tools.qr "$(SLUG)" $(ARGS)
