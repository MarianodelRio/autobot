#!/usr/bin/env bash
# Deploy a published, immutable image. Run on the VPS as the deploy user only.
set -euo pipefail

cd "$(dirname "$0")/.."
exec 9>.deploy.lock
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }

if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: deploy/deploy.sh <full-40-character-sha>' >&2
  exit 2
fi
target=$1
previous=$(cat .deployed-sha 2>/dev/null || true)
if [[ -n $previous && ! $previous =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Invalid .deployed-sha; refusing deploy' >&2
  exit 1
fi
export SHA="$target"
compose=(docker compose --project-name flowpilot -f compose.prod.yaml)

wait_health() {
  local deadline=$((SECONDS + 60)) response attempt
  for ((attempt=0; attempt<30 && SECONDS<deadline; attempt++)); do
    if response=$(curl --silent --show-error --fail --max-time 2 http://127.0.0.1:8000/health 2>/dev/null) && \
      python3 -c 'import json,sys; r=json.load(sys.stdin); t=r["tenants"]; assert r["status"] == "ok" and t["degraded"] == 0 and t["unreadable"] == 0' <<<"$response" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

if [[ $previous == "$target" ]]; then
  if wait_health; then
    echo 'Already deployed and healthy'
    exit 0
  fi
  echo 'Recorded image is unhealthy; restarting services' >&2
  "${compose[@]}" up --no-deps -d web worker
  wait_health
  exit $?
fi

# The first deployment needs PostgreSQL before a one-shot migration container.
"${compose[@]}" up -d --wait db
"${compose[@]}" pull web worker
"${compose[@]}" run --rm web python manage.py migrate --noinput
"${compose[@]}" run --rm web python manage.py sync_tenants --strict

rollback() {
  echo 'New web failed health check; restoring previous image' >&2
  if [[ -n $previous ]]; then
    export SHA="$previous"
    if [[ -d .git ]] && ! git checkout --quiet --detach "$previous"; then
      echo 'Could not restore previous repository configuration' >&2
    fi
    if ! "${compose[@]}" up --no-deps -d web worker; then
      echo 'Could not restart previous image; operator action required' >&2
    fi
    if ! wait_health; then
      echo 'Rollback health check failed; operator action required' >&2
    fi
    if ! "${compose[@]}" up --no-deps -d caddy; then
      echo 'Could not restart Caddy; operator action required' >&2
    fi
  else
    echo 'No previous SHA; first deployment needs operator action' >&2
  fi
  # One attempt only: ambiguous Telegram delivery must not be retried blindly.
  "${compose[@]}" run --rm web python manage.py shell -c \
    "from flowpilot.runtime.notifications import send_ops_alert; send_ops_alert('deploy_rollback', None, '🔴 Despliegue fallido: revisar estado de salud')" \
    || echo 'Could not send ops alert; check deployment logs' >&2
  exit 1
}

"${compose[@]}" up --no-deps -d web worker || rollback
wait_health || rollback
"${compose[@]}" up --no-deps -d caddy || rollback
printf '%s\n' "$target" >.deployed-sha.tmp
mv .deployed-sha.tmp .deployed-sha
echo "Deployed $target"
