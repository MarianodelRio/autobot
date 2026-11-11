#!/usr/bin/env bash
# Deploy a published, immutable image. Run on the VPS as the deploy user only.
set -euo pipefail

cd "$(dirname "$0")/../.."
mkdir -p var/state/ops
exec 9>var/.deploy.lock
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }

if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: deploy/scripts/deploy.sh <full-40-character-sha>' >&2
  exit 2
fi
# .env on disk is enough: docker compose reads it itself for ${VAR:?} substitution.
deploy/scripts/ensure-env.sh
target=$1
previous=$(cat var/.deployed-sha 2>/dev/null || true)
if [[ -n $previous && ! $previous =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Invalid var/.deployed-sha; refusing deploy' >&2
  exit 1
fi
export SHA="$target"
compose=(docker compose --project-name autobot -f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml)

# A tenant already degraded before this deploy must never block it, including pausing
# it (X10): only a tenant that becomes degraded *because of this deploy* does. Best
# effort: unreachable (e.g. the first deployment) counts as no pre-existing ones.
baseline_degraded=0
if response=$(curl --silent --show-error --fail --max-time 2 http://127.0.0.1:8000/health/internal 2>/dev/null); then
  baseline_degraded=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tenants"]["degraded"])' \
    <<<"$response" 2>/dev/null) || baseline_degraded=0
fi

wait_health() {
  local deadline=$((SECONDS + 60)) response attempt
  for ((attempt=0; attempt<30 && SECONDS<deadline; attempt++)); do
    if response=$(curl --silent --show-error --fail --max-time 2 http://127.0.0.1:8000/health/internal 2>/dev/null) && \
      python3 -c 'import json,sys; r=json.load(sys.stdin); t=r["tenants"]
assert r["status"] == "ok" and t["degraded"] <= int(sys.argv[1]) and t["unreadable"] == 0' \
        "$baseline_degraded" <<<"$response" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_panel() {
  local deadline=$((SECONDS + 60))
  while ((SECONDS < deadline)); do
    curl --silent --show-error --fail --max-time 2 http://127.0.0.1:8080/healthz >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# Neither worker has an HTTP endpoint: a crash at start shows as a stopped container or
# a restart under `restart: unless-stopped`, so each must stay up and unrestarted for
# ~10 s (X14: inbound and outbound/periodic are now two separate workers).
wait_worker() {
  local service id sample
  for service in worker-inbound worker-outbound; do
    id=$("${compose[@]}" ps -q "$service") || return 1
    [[ -n $id ]] || return 1
    for sample in 1 2 3 4 5; do
      [[ $(docker inspect -f '{{.State.Running}} {{.RestartCount}}' "$id") == 'true 0' ]] || return 1
      [[ $sample == 5 ]] || sleep 2
    done
  done
}

restore_checkout() {
  if [[ -n $previous && -d .git ]] && ! git checkout --quiet --detach "$previous"; then
    echo 'Could not restore previous repository configuration' >&2
  fi
}

# One attempt only: ambiguous Telegram delivery must not be retried blindly. A third
# argument of "informational" skips the cooldown and is saved already resolved.
alert_ops() {
  local informational=False
  [[ ${3:-} == informational ]] && informational=True
  "${compose[@]}" run --rm web python manage.py shell -c \
    "from autobot.runtime.notifications import send_ops_alert; send_ops_alert('$1', None, '$2', informational=$informational)" \
    || echo 'Could not send ops alert; check deployment logs' >&2
}

# One line per attempt, read by the panel; `web` mounts var/state/ops read-only.
record_deploy() {
  printf '{"at":"%s","sha":"%s","previous":"%s","result":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$target" "$previous" "$1" >>var/state/ops/deploys.jsonl
}

if [[ $previous == "$target" ]]; then
  if wait_health; then
    echo 'Already deployed and healthy'
    record_deploy already
    exit 0
  fi
  echo 'Recorded image is unhealthy; restarting services' >&2
  "${compose[@]}" up --no-deps -d web worker-inbound worker-outbound panel
  if wait_health && wait_panel; then
    record_deploy already
    exit 0
  fi
  record_deploy rollback_failed
  exit 1
fi

# A failure before switching images leaves the previous containers running: only the
# checkout made by ssh-deploy.sh must go back, so files match what is running.
abort() {
  echo 'Deployment failed before switching images; previous image kept' >&2
  restore_checkout
  if [[ -n $previous ]]; then
    export SHA="$previous"  # the new image may not even have been pulled
  fi
  # init-roles.sh (just run, or mid-way through) may have left fp_app with the broad
  # grants it starts with; reapply the real ones so an aborted deploy never leaves them.
  "${compose[@]}" run --rm web python manage.py apply_grants \
    || echo 'Could not reapply grants after aborting; fp_app may still have broad permissions' >&2
  alert_ops deploy_aborted '🔴 Despliegue abortado antes de cambiar la imagen: revisar logs'
  record_deploy aborted
  exit 1
}

# The first deployment needs PostgreSQL before a one-shot migration container.
"${compose[@]}" up -d --wait db || abort
"${compose[@]}" exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh || abort
"${compose[@]}" pull web worker-inbound worker-outbound panel || abort
# Logs are not critical: victorialogs never aborts or rolls back a deployment.
"${compose[@]}" pull victorialogs || echo 'Could not pull victorialogs; logs will be unavailable' >&2
"${compose[@]}" up -d victorialogs || echo 'Could not start victorialogs; logs will be unavailable' >&2
"${compose[@]}" run --rm web python manage.py migrate --noinput || abort
"${compose[@]}" run --rm web python manage.py apply_grants || abort
"${compose[@]}" run --rm web python manage.py tenant_config validate --all || abort
"${compose[@]}" run --rm web python manage.py seed_demos || abort

rollback() {
  echo 'New image failed its health checks; restoring previous image' >&2
  local result=rollback_failed
  if [[ -n $previous ]]; then
    export SHA="$previous"
    restore_checkout
    local failed=0
    if ! "${compose[@]}" up --no-deps -d web worker-inbound worker-outbound panel; then
      echo 'Could not restart previous image; operator action required' >&2
      failed=1
    fi
    if ! wait_health; then
      echo 'Rollback health check failed; operator action required' >&2
      failed=1
    fi
    if ! wait_worker; then
      echo 'Rollback worker check failed; operator action required' >&2
      failed=1
    fi
    if ! wait_panel; then
      echo 'Rollback panel check failed; operator action required' >&2
      failed=1
    fi
    if ! "${compose[@]}" up --no-deps -d caddy; then
      echo 'Could not restart Caddy; operator action required' >&2
      failed=1
    fi
    [[ $failed -eq 0 ]] && result=rolled_back
  else
    echo 'No previous SHA; first deployment needs operator action' >&2
  fi
  alert_ops deploy_rollback '🔴 Despliegue fallido: revisar estado de salud'
  record_deploy "$result"
  exit 1
}

# --remove-orphans: drops containers of services no longer defined (the single
# `worker` from before X14), which would otherwise keep running the old image.
"${compose[@]}" up --no-deps --remove-orphans -d web worker-inbound worker-outbound panel || rollback
wait_health || rollback
wait_worker || rollback
wait_panel || rollback
"${compose[@]}" up --no-deps -d caddy || rollback
printf '%s\n' "$target" >var/.deployed-sha.tmp
mv var/.deployed-sha.tmp var/.deployed-sha
record_deploy deployed
alert_ops deploy_ok "🟢 Desplegado ${target:0:7}" informational
echo "Deployed $target"
