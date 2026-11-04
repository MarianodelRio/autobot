HOST ?= autobot
NGROK_DOMAIN ?= unpermanently-repairable-devon.ngrok-free.dev

.PHONY: up down test check shell telegram-poll bus-validar bus-formatear bus-revision bus-publicar
.PHONY: status logs tenant-health qr check-prod-config deploy backup-now restore-test
.PHONY: db-roles api fix panel-dev panel-check

check-prod-config:
	uv run python tools/check_prod_config.py

api:
	uv run python manage.py export_openapi panel/openapi.json
	pnpm -C panel gen:api

fix:
	uv run ruff check --fix .
	uv run ruff format .
	pnpm -C panel fix
	$(MAKE) api

panel-dev:
	pnpm -C panel dev

panel-check:
	pnpm -C panel check
	pnpm -C panel typecheck
	pnpm -C panel test
	pnpm -C panel build

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

# Bus tools operate on ignored exports under datos/<slug>/.
BUS_TOOL = PYTHONPATH=src uv run python -m tools
export TENANT COMMENT PROD

bus-bajar:
	$(BUS_TOOL).bus_data download

bus-validar:
	$(BUS_TOOL).bus_validar $(TENANT)

bus-formatear:
	$(BUS_TOOL).bus_formatear $(TENANT)

bus-revision:
	$(BUS_TOOL).bus_revision $(TENANT) $(ARGS)

bus-publicar:
	$(BUS_TOOL).bus_data publish

tenant-health:
	docker compose exec web python manage.py tenant_health $(SLUG)

# Public QR generated on the developer machine, without containers or secrets.
qr:
	PYTHONPATH=src uv run python -m tools.qr "$(FILE)" $(ARGS)

.PHONY: prod-manage tenant-push bus-bajar
export HOST SLUG SECRETS

prod-manage:
	@ssh $(if $(TTY),-t,) deploy@$(HOST) /srv/autobot/deploy/manage.sh $(CMD)

tenant-push:
	bash tools/tenant_push.sh

.PHONY: dev-bootstrap dev-reset dev-activity tenant-import ngrok
export DIR

dev-bootstrap:
	docker compose up -d --wait db
	$(MAKE) db-roles
	docker compose build web
	docker compose run --rm -T web python manage.py migrate --database owner --noinput
	docker compose run --rm -T web python manage.py apply_grants
	docker compose run --rm -T web python manage.py seed_demos
	docker compose run --rm -T web python manage.py panel_user exists panel \
		|| docker compose run --rm web python manage.py panel_user create panel
	docker compose up -d --no-build web worker victorialogs

dev-reset:
	@read -r -p "Borrar la BD local y reiniciar (escribe RESET): " answer; test "$$answer" = RESET
	docker compose down -v
	$(MAKE) dev-bootstrap

dev-activity:
	docker compose exec web python manage.py seed_dev_activity

tenant-import:
	bash tools/tenant_import.sh

ngrok:
	ngrok http --domain=$(NGROK_DOMAIN) 8000
