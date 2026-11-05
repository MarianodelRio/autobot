HOST ?= autobot
NGROK_DOMAIN ?= unpermanently-repairable-devon.ngrok-free.dev

.DEFAULT_GOAL := help

# apps/backend is self-contained (its own pyproject.toml, uv.lock, .venv, tests/);
# backend tooling runs from inside it, while targets whose relative paths (datos/,
# tenants/, var/) are anchored at the repo root run from here with --project.
BACKEND = cd apps/backend &&
PYTEST = $(BACKEND) uv run pytest

##@ Ayuda

help: ## Enseña esta ayuda
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Desarrollo

.PHONY: up down status db-roles logs shell telegram-poll dev-bootstrap dev-reset dev-activity tenant-import ngrok

up: ## Tras el bootstrap, levanta los contenedores
	docker compose up -d --build

down: ## Para los contenedores
	docker compose down

status: ## docker compose ps
	docker compose ps

# Creates fp_owner, fp_app and fp_readonly (or updates their passwords) without
# recreating the db container; needed after adding a role or rotating a password.
db-roles: ## Reaplica roles y contraseñas de PostgreSQL sin recrear el contenedor
	docker compose exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh

logs: ## Sigue los logs de un servicio (SERVICE=<servicio>)
	docker compose logs --tail=100 --follow $(SERVICE)

shell: ## Abre una shell de Django dentro de `web`
	docker compose exec web python manage.py shell

# Long polling of a tenant's own bot (SLUG=<slug>), e.g. to record Telegram
# fixtures. Needs the worker running (`make up`) and no webhook set on that bot.
# Local development of the demo bot's Telegram door uses a webhook through ngrok
# instead (see docs/runbooks/demo.md), the same mechanism as production.
telegram-poll: ## Long polling del bot de Telegram de un tenant (SLUG=<slug>)
	docker compose exec web python manage.py telegram_poll $(SLUG)

export DIR

dev-bootstrap: ## Prepara BD, roles, migra, siembra demos y levanta web/worker
	docker compose up -d --wait db
	$(MAKE) db-roles
	docker compose build web
	docker compose run --rm -T web python manage.py migrate --database owner --noinput
	docker compose run --rm -T web python manage.py apply_grants
	docker compose run --rm -T web python manage.py seed_demos
	docker compose run --rm -T web python manage.py panel_user exists panel \
		|| docker compose run --rm web python manage.py panel_user create panel
	docker compose up -d --no-build web worker victorialogs

dev-reset: ## Exige escribir RESET, borra el volumen local y repite el bootstrap
	@read -r -p "Borrar la BD local y reiniciar (escribe RESET): " answer; test "$$answer" = RESET
	docker compose down -v
	$(MAKE) dev-bootstrap

dev-activity: ## Crea actividad falsa en local para ver el panel con datos
	docker compose exec web python manage.py seed_dev_activity

tenant-import: ## Importa un directorio contra la BD local (DIR=<dir> [SECRETS=<yaml>])
	bash apps/backend/src/tools/tenant_import.sh

ngrok: ## Abre el túnel al puerto 8000 ([NGROK_DOMAIN=<dominio>])
	ngrok http --domain=$(NGROK_DOMAIN) 8000

##@ Calidad

.PHONY: test test-fast check fix api

test: ## uv run pytest
	$(PYTEST)

test-fast: ## pytest -m "not db", sin base de datos levantada
	$(PYTEST) -m "not db"

check: ## Puerta de calidad del backend: ruff, mypy, import-linter, pytest
	$(BACKEND) uv run ruff check .
	$(BACKEND) uv run ruff format --check .
	$(BACKEND) uv run mypy
	$(BACKEND) PYTHONPATH=src uv run lint-imports
	$(PYTEST)

fix: ## Aplica ruff y biome, y regenera la API del panel
	$(BACKEND) uv run ruff check --fix .
	$(BACKEND) uv run ruff format .
	pnpm -C apps/panel fix
	$(MAKE) api

api: ## Regenera el esquema OpenAPI del panel y sus tipos TypeScript
	$(BACKEND) uv run python manage.py export_openapi ../panel/openapi.json
	pnpm -C apps/panel gen:api

##@ Panel

.PHONY: panel-dev panel-check panel-tunnel

panel-dev: ## Vite en modo desarrollo, con proxy /api hacia el backend local
	pnpm -C apps/panel dev

panel-check: ## Puerta de calidad del frontend: biome, tsc, vitest y el build
	pnpm -C apps/panel check
	pnpm -C apps/panel typecheck
	pnpm -C apps/panel test
	pnpm -C apps/panel build

# SSH tunnel to the panel container's own port (8080), never to `web` directly.
panel-tunnel: ## Túnel SSH al puerto del contenedor panel en producción ([HOST=<servidor>])
	ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18000:127.0.0.1:8080 deploy@$(HOST)

##@ Negocios

.PHONY: tenant-health qr check-prod-config tenant-push

tenant-health: ## Comprueba y persiste la salud del pack y del canal (SLUG=<slug>)
	docker compose exec web python manage.py tenant_health $(SLUG)

# Public QR generated on the developer machine, without containers or secrets.
qr: ## Genera el QR a partir de un documento exportado (FILE=<document.yaml>)
	PYTHONPATH=apps/backend/src uv run --project apps/backend python -m tools.qr "$(FILE)" $(ARGS)

check-prod-config: ## Prueba el allowlist de Caddy contra un upstream local
	uv run --project apps/backend python apps/backend/src/tools/check_prod_config.py

export HOST SLUG SECRETS

tenant-push: ## Exporta la BD local y la importa por SSH (SLUG=<slug> [SECRETS=<yaml>])
	bash apps/backend/src/tools/tenant_push.sh

##@ Bus

# Bus tools operate on ignored exports under datos/<slug>/.
BUS_TOOL = PYTHONPATH=apps/backend/src uv run --project apps/backend python -m tools
export TENANT COMMENT PROD

.PHONY: bus-bajar bus-validar bus-formatear bus-revision bus-publicar

bus-bajar: ## Exporta el dataset vigente a datos/<slug>/timetable (TENANT=<slug> [PROD=1])
	$(BUS_TOOL).bus_data download

bus-validar: ## Valida datos/<slug>/timetable (TENANT=<slug>)
	$(BUS_TOOL).bus_validar $(TENANT)

bus-formatear: ## Realinea las columnas de las tablas de horarios (TENANT=<slug>)
	$(BUS_TOOL).bus_formatear $(TENANT)

bus-revision: ## Genera HTML/PDF comparando con .publicado (TENANT=<slug> [ARGS="..."])
	$(BUS_TOOL).bus_revision $(TENANT) $(ARGS)

bus-publicar: ## Publica la copia local validada en BD (TENANT=<slug> COMMENT="..." [PROD=1])
	$(BUS_TOOL).bus_data publish

##@ Producción

SHA ?= $(shell git rev-parse origin/main)

.PHONY: deploy rollback backup-now restore-test prod-manage

deploy: ## Lanza el despliegue si el CI del SHA está en verde ([SHA=])
	@conclusion=$$(gh run list --workflow ci.yml --commit $(SHA) --json conclusion -q '.[0].conclusion'); \
	if [ "$$conclusion" != success ]; then \
		echo "CI for $(SHA) is not green (got: '$$conclusion'); refusing to deploy" >&2; \
		exit 1; \
	fi
	gh workflow run deploy.yml -f sha="$(SHA)"

# Reads the last successful deployment's `previous` SHA from the server and redeploys
# it, with confirmation. Needs the operation SSH key (`~/.ssh/config` alias $(HOST)).
rollback: ## Redespliega el `previous` del último despliegue correcto, con confirmación
	@previous=$$(ssh deploy@$(HOST) 'tail -n 50 /srv/autobot/state/ops/deploys.jsonl' | \
		python3 -c "import json, sys; entries = [json.loads(line) for line in sys.stdin if line.strip()]; deployed = [e for e in entries if e['result'] == 'deployed']; print(deployed[-1]['previous'] if deployed else '')"); \
	if [ -z "$$previous" ]; then \
		echo 'No previous successful deployment found to roll back to' >&2; \
		exit 1; \
	fi; \
	read -r -p "Roll back to $$previous? [y/N] " confirm; \
	[ "$$confirm" = y ] || exit 1; \
	$(MAKE) deploy SHA=$$previous

backup-now: ## Ejecuta deploy/backup.sh en el servidor por SSH
	ssh deploy@$(HOST) /srv/autobot/deploy/backup.sh

restore-test: ## Simulacro de restauración (bash deploy/restore-test.sh)
	bash deploy/restore-test.sh

prod-manage: ## Ejecuta un comando de manage.py contra la imagen desplegada (CMD="..." [TTY=1])
	@ssh $(if $(TTY),-t,) deploy@$(HOST) /srv/autobot/deploy/manage.sh $(CMD)
