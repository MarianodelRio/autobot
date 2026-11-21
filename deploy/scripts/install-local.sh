#!/usr/bin/env bash
# One command to bring the whole local stack up, from scratch or from a previous
# state, without deleting any data (`make local`): requirements, .env, db, roles,
# build, migrations, grants, demo tenants, services and a health check. Replaces the
# body of the old `make dev-bootstrap`. Idempotent; `make dev-reset` is the only
# thing that wipes the local database.
#
# Usage: deploy/scripts/install-local.sh [--check] [--skip-panel-user]
set -euo pipefail
cd "$(dirname "$0")/../.."

check_only=false
skip_panel_user=false
for arg in "$@"; do
  case $arg in
  --check) check_only=true ;;
  --skip-panel-user) skip_panel_user=true ;;
  *) echo 'Uso: deploy/scripts/install-local.sh [--check] [--skip-panel-user]' >&2; exit 2 ;;
  esac
done

# Pinned: the local stack always uses the local compose files, even if an old .env
# still lists the production ones.
export COMPOSE_FILE=deploy/compose/compose.yaml:deploy/compose/compose.local.yaml
export COMPOSE_PROJECT_NAME=autobot

missing=()
command -v docker >/dev/null 2>&1 || missing+=('docker')
command -v curl >/dev/null 2>&1 || missing+=('curl')
if command -v docker >/dev/null 2>&1; then
  docker compose version >/dev/null 2>&1 || missing+=('docker compose (plugin v2)')
  docker info >/dev/null 2>&1 || missing+=('un daemon de Docker accesible para tu usuario')
fi
if ((${#missing[@]})); then
  echo "Faltan requisitos: ${missing[*]}" >&2
  exit 1
fi
echo 'Requisitos: ok (docker, docker compose, curl)'

if [[ ! -f .env ]]; then
  if [[ $check_only == true ]]; then
    echo '.env: falta (se crearía desde .env.example)'
  else
    # Only the documented local defaults; no third-party credential is invented.
    install -m 600 .env.example .env
    echo '.env creado desde .env.example (valores locales; los tokens de Telegram/Meta quedan vacíos)'
  fi
else
  echo '.env: ya existe, no se toca'
fi

health() {
  local response
  response=$(curl --silent --fail --max-time 3 http://127.0.0.1:8000/health/internal) &&
    python3 -c 'import json, sys
r = json.load(sys.stdin)
assert r["status"] == "ok" and r["tenants"]["unreadable"] == 0' <<<"$response" 2>/dev/null
}

if [[ $check_only == true ]]; then
  if health; then echo 'Estado: web responde y está sana'; else echo 'Estado: web no responde (make local la levanta)'; exit 1; fi
  exit 0
fi

docker compose up -d --wait db
docker compose exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh
docker compose build web
docker compose run --rm -T web python manage.py migrate --database owner --noinput
docker compose run --rm -T web python manage.py apply_grants
docker compose run --rm -T web python manage.py seed_demos
if [[ $skip_panel_user != true ]]; then
  if docker compose run --rm -T web python manage.py panel_user exists panel; then
    echo 'Usuario del panel: ya existe'
  elif [[ -t 0 ]]; then
    docker compose run --rm web python manage.py panel_user create panel
  else
    echo 'Usuario del panel: pendiente (terminal no interactivo); ejecuta: docker compose run --rm web python manage.py panel_user create panel'
  fi
fi
docker compose up -d --no-build --remove-orphans web worker-inbound worker-outbound victorialogs

for ((i = 0; i < 30; i++)); do
  health && break
  sleep 2
done
if ! health; then
  # shellcheck disable=SC2016 # literal backticks/$() in a message
  echo 'web no quedó sana en 60 s: revisa `make logs SERVICE=web`' >&2
  exit 1
fi
for service in worker-inbound worker-outbound; do
  if [[ -z $(docker compose ps -q --status running "$service") ]]; then
    echo "$service no está en marcha: revisa make logs SERVICE=$service" >&2
    exit 1
  fi
done
echo 'Todo en marcha: web http://127.0.0.1:8000 (health ok), workers y logs levantados.'
