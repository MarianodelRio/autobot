HOST ?= autobot
NGROK_DOMAIN ?= $(shell sed -n 's/^NGROK_DOMAIN=//p' .env 2>/dev/null)

.DEFAULT_GOAL := help

# apps/backend is self-contained (its own pyproject.toml, uv.lock, .venv, tests/);
# backend tooling runs from inside it, while targets whose relative paths (var/datos/,
# var/tenants/) are anchored at the repo root run from here with --project.
# DJANGO_SETTINGS_MODULE: local tools run with ENVIRONMENT=local (config.settings alone
# treats an unset ENVIRONMENT as prod).
# Variables passed to the scripts and tools the targets run.
export DIR HOST SLUG SECRETS

BACKEND = cd apps/backend && DJANGO_SETTINGS_MODULE=config.settings_dev
PYTEST = $(BACKEND) uv run pytest

##@ Ayuda

help: ## Enseña esta ayuda
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Desarrollo

.PHONY: help up down status db-roles logs shell telegram-poll chat local dev-bootstrap dev-reset dev-activity tenant-import ngrok

up: ## Construye y levanta los contenedores de desarrollo (docker compose up -d --build)
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
# instead (see docs/procedimientos/demo.md), the same mechanism as production.
telegram-poll: ## Long polling del bot de Telegram de un tenant (SLUG=<slug>)
	docker compose exec web python manage.py telegram_poll $(SLUG)

# chat de prueba sobre la plantilla de demo de un pack, sin canal real ni BD
# (core.testing.Conversation). No necesita `make up` ni ningún contenedor.
chat: ## Chat de prueba por terminal con un pack (PACK=salon|bus [CHANNEL=telegram])
	$(BACKEND) uv run python manage.py chat $(PACK) $(if $(CHANNEL),--channel $(CHANNEL),)

# Un solo comando para dejarlo todo funcionando en local, desde cero o desde un estado
# previo, sin borrar datos (deploy/scripts/install-local.sh; ADR-017).
local: ## Deja todo el entorno local funcionando (requisitos, .env, BD, migraciones, demos, servicios, salud)
	bash deploy/scripts/install-local.sh $(ARGS)

dev-bootstrap: local ## Alias de `make local`

dev-reset: ## Exige escribir RESET, borra el volumen local y repite `make local`
	@read -r -p "Borrar la BD local y reiniciar (escribe RESET): " answer; test "$$answer" = RESET
	docker compose down -v
	$(MAKE) local

dev-activity: ## Crea actividad falsa en local para ver el panel con datos
	docker compose exec web python manage.py seed_dev_activity

tenant-import: ## Importa un directorio contra la BD local (DIR=<dir> [SECRETS=<yaml>])
	bash apps/backend/src/tools/tenant/tenant_import.sh

ngrok: ## Abre el túnel al puerto 8000 (NGROK_DOMAIN en .env o en la línea de comandos)
	@test -n "$(NGROK_DOMAIN)" || { echo 'Set NGROK_DOMAIN in .env (your reserved ngrok domain)' >&2; exit 1; }
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

api: ## Regenera el esquema OpenAPI del panel, sus tipos TypeScript y docs/referencia/api-panel.md
	$(BACKEND) uv run python manage.py export_openapi ../panel/openapi.json
	cd apps/backend && PYTHONPATH=src uv run python -m tools.docs.openapi_md
	pnpm -C apps/panel gen:api

##@ Documentación

.PHONY: docs docs-check

# Zensical reads mkdocs.yml at the repo root and must run from there: the snippets
# (`--8<--`) resolve their paths against the working directory. The tool lives in the
# backend's `docs` dependency group (ADR-018).
DOCS = uv run --project apps/backend --group docs zensical

docs: ## Sirve la documentación en local con recarga (http://localhost:8100)
	$(DOCS) serve -f mkdocs.yml -a localhost:8100

docs-check: ## Construye la documentación en modo estricto (los enlaces rotos fallan)
	$(DOCS) build --strict -f mkdocs.yml

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
	PYTHONPATH=apps/backend/src uv run --project apps/backend python -m tools.ops.qr "$(FILE)" $(ARGS)

check-prod-config: ## Prueba el allowlist de Caddy contra un upstream local
	uv run --project apps/backend python apps/backend/src/tools/ops/check_prod_config.py

tenant-push: ## Exporta la BD local y la importa por SSH (SLUG=<slug> [SECRETS=<yaml>])
	bash apps/backend/src/tools/tenant/tenant_push.sh

##@ Bus

# Bus tools operate on ignored exports under var/datos/<slug>/.
BUS_TOOL = PYTHONPATH=apps/backend/src uv run --project apps/backend python -m tools
export COMMENT PROD NOMBRE VERSION

.PHONY: bus-bajar bus-validar bus-formatear bus-revision bus-subir

bus-bajar: ## Descarga una entrada de la biblioteca a var/datos/<nombre>/timetable (ADR-013; NOMBRE=<nombre> [VERSION=<n>] [PROD=1])
	$(BUS_TOOL).bus.library pull

bus-validar: ## Valida var/datos/<nombre>/timetable (NOMBRE=<nombre>)
	$(BUS_TOOL).bus.validar $(NOMBRE)

bus-formatear: ## Realinea las columnas de las tablas de horarios (NOMBRE=<nombre>)
	$(BUS_TOOL).bus.formatear $(NOMBRE)

bus-revision: ## Genera HTML/PDF comparando con .publicado (NOMBRE=<nombre> [ARGS="..."])
	$(BUS_TOOL).bus.revision $(NOMBRE) $(ARGS)

bus-subir: ## Sube horarios validados a la biblioteca (ADR-013); nunca toca a ningún cliente (NOMBRE=<nombre> DIR=<dir> COMMENT="..." [PROD=1])
	$(BUS_TOOL).bus.library push

##@ Entorno local completo (localprod)

.PHONY: localprod-up localprod-backup localprod-restore localprod-down

# reproduce producción en local -- Caddy con TLS, DEPLOY_UID real, gunicorn,
# deploy.sh real, con un registro Docker local en vez de GHCR; proyecto, puertos y
# volúmenes aparte de los de desarrollo (nunca choca con `make up`).
localprod-up: ## Instala/actualiza el entorno localprod con el deploy.sh real
	bash deploy/scripts/localprod.sh up

localprod-backup: ## backup.sh real contra un repositorio restic en disco (var/localprod/)
	bash deploy/scripts/localprod.sh backup

localprod-restore: ## restore.sh real; reemplaza el volumen de BD de localprod
	bash deploy/scripts/localprod.sh restore

localprod-down: ## Para y borra los contenedores y el registro local de localprod
	bash deploy/scripts/localprod.sh down

##@ Instalación y traslado

.PHONY: install-vm server-migrate

# ADR-017: se ejecuta DENTRO de la VM (clon del repo + sudo), no desde el portátil; el
# make está aquí solo para documentarlo y para probarlo en la VM. Idempotente.
install-vm: ## Instala/repara la VM de producción; ejecutar dentro de la VM (ARGS="--public-host ... --google-sa ...")
	sudo bash deploy/scripts/install-vm.sh $(ARGS)

# FROM y TO son alias de ~/.ssh/config o IPs; TO ya debe tener el bootstrap hecho
# (install-vm.sh --restore-target, dentro de TO). Ver docs/procedimientos/servidor.md y ADR-012.
server-migrate: ## Traslada el despliegue de FROM a TO (FROM= TO= [ONLY=paso])
	bash deploy/scripts/server-migrate.sh $(FROM) $(TO) $(if $(ONLY),--only=$(ONLY),)

##@ Producción

SHA ?= $(shell git rev-parse origin/main)

.PHONY: deploy rollback backup-now backup-prune restore-test prod-manage prod-compose

deploy: ## Lanza el despliegue si el CI del SHA está en verde ([SHA=])
	@conclusion=$$(gh run list --workflow ci.yml --commit $(SHA) --json conclusion -q '.[0].conclusion'); \
	if [ "$$conclusion" != success ]; then \
		echo "CI for $(SHA) is not green (got: '$$conclusion'); refusing to deploy" >&2; \
		exit 1; \
	fi
	gh workflow run deploy.yml -f sha="$(SHA)"

# Reads the last successful deployment's `previous` SHA from the server and redeploys
# it, with confirmation. Needs the operation SSH key (`~/.ssh/config` alias $(HOST)).
# rollback_target.py refuses a second rollback in a row: it would otherwise
# redeploy the broken SHA the first rollback just moved away from.
rollback: ## Redespliega el `previous` del último despliegue correcto, con confirmación
	@previous=$$(ssh deploy@$(HOST) 'tail -n 50 /srv/autobot/var/state/ops/deploys.jsonl' | \
		python3 deploy/scripts/rollback_target.py) || exit 1; \
	read -r -p "Roll back to $$previous? [y/N] " confirm; \
	[ "$$confirm" = y ] || exit 1; \
	$(MAKE) deploy SHA=$$previous

backup-now: ## Ejecuta deploy/scripts/backup.sh en el servidor por SSH
	ssh deploy@$(HOST) /srv/autobot/deploy/scripts/backup.sh

backup-prune: ## Caduca snapshots viejos desde TU máquina, con otra credencial (ARGS="--dry-run")
	bash deploy/scripts/backup-prune.sh $(ARGS)

restore-test: ## Simulacro de restauración (bash deploy/scripts/restore-test.sh)
	bash deploy/scripts/restore-test.sh

prod-manage: ## Ejecuta un comando de manage.py contra la imagen desplegada (CMD="..." [TTY=1])
	@ssh $(if $(TTY),-t,) deploy@$(HOST) /srv/autobot/deploy/scripts/manage.sh $(CMD)

# For anything manage.sh doesn't cover (`exec`, `logs`...); SHA and --env-file come
# from deploy/scripts/lib.sh, so a bare `docker compose exec web ...` never needs them.
prod-compose: ## Ejecuta un comando de docker compose contra el servidor (ARGS="..." [TTY=1])
	@ssh $(if $(TTY),-t,) deploy@$(HOST) /srv/autobot/deploy/scripts/compose.sh $(ARGS)
