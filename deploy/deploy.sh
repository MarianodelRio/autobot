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

# The worker has no HTTP endpoint: a crash at start shows as a stopped container or a
# restart under `restart: unless-stopped`, so it must stay up and unrestarted for ~10 s.
wait_worker() {
  local id sample
  id=$("${compose[@]}" ps -q worker) || return 1
  [[ -n $id ]] || return 1
  for sample in 1 2 3 4 5; do
    [[ $(docker inspect -f '{{.State.Running}} {{.RestartCount}}' "$id") == 'true 0' ]] || return 1
    [[ $sample == 5 ]] || sleep 2
  done
}

restore_checkout() {
  if [[ -n $previous && -d .git ]] && ! git checkout --quiet --detach "$previous"; then
    echo 'Could not restore previous repository configuration' >&2
  fi
}

# One attempt only: ambiguous Telegram delivery must not be retried blindly.
alert_ops() {
  "${compose[@]}" run --rm web python manage.py shell -c \
    "from flowpilot.runtime.notifications import send_ops_alert; send_ops_alert('$1', None, '$2')" \
    || echo 'Could not send ops alert; check deployment logs' >&2
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

# A failure before switching images leaves the previous containers running: only the
# checkout made by ssh-deploy.sh must go back, so files match what is running.
abort() {
  echo 'Deployment failed before switching images; previous image kept' >&2
  restore_checkout
  if [[ -n $previous ]]; then
    export SHA="$previous"  # the new image may not even have been pulled
  fi
  alert_ops deploy_aborted '🔴 Despliegue abortado antes de cambiar la imagen: revisar logs'
  exit 1
}

# The first deployment needs PostgreSQL before a one-shot migration container.
"${compose[@]}" up -d --wait db || abort
"${compose[@]}" pull web worker || abort
"${compose[@]}" run --rm web python manage.py migrate --noinput || abort
"${compose[@]}" run --rm web python manage.py sync_tenants --strict || abort

rollback() {
  echo 'New image failed its health checks; restoring previous image' >&2
  if [[ -n $previous ]]; then
    export SHA="$previous"
    restore_checkout
    if ! "${compose[@]}" up --no-deps -d web worker; then
      echo 'Could not restart previous image; operator action required' >&2
    fi
    if ! wait_health; then
      echo 'Rollback health check failed; operator action required' >&2
    fi
    if ! wait_worker; then
      echo 'Rollback worker check failed; operator action required' >&2
    fi
    if ! "${compose[@]}" up --no-deps -d caddy; then
      echo 'Could not restart Caddy; operator action required' >&2
    fi
  else
    echo 'No previous SHA; first deployment needs operator action' >&2
  fi
  alert_ops deploy_rollback '🔴 Despliegue fallido: revisar estado de salud'
  exit 1
}

"${compose[@]}" up --no-deps -d web worker || rollback
wait_health || rollback
wait_worker || rollback
"${compose[@]}" up --no-deps -d caddy || rollback
printf '%s\n' "$target" >.deployed-sha.tmp
mv .deployed-sha.tmp .deployed-sha
echo "Deployed $target"
