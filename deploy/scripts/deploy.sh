#!/usr/bin/env bash
# Deploy a published, immutable image. Run on the VPS as the deploy user only.
set -euo pipefail
# deploy.yml runs this over SSH; if the connection drops mid-run, bash would
# otherwise receive SIGHUP and die before switching images, rolling back or
# writing deploys.jsonl. Ignore it instead: there is no sudo access on this host
# to detach the process with systemd-run, so this is the one thing that can be
# done locally to keep a deploy from being abandoned half-done by a dropped link.
trap '' HUP

# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
mkdir -p var/state/ops
exec 9>var/.deploy.lock
# containers.sh only probes this lock in shared mode for microseconds; wait instead
# of failing instantly so it can never collide with a real deployment.
flock -w 10 9 || { echo 'Another deployment is running' >&2; exit 1; }

if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: deploy/scripts/deploy.sh <full-40-character-sha>' >&2
  exit 2
fi
# T4: server-migrate.sh creates var/.frozen on the origin right before the cutover,
# so that nothing (CI, an operator, a cron) can deploy there while the destination
# is taking over; also checked by restore.sh.
if [[ -f var/.frozen ]]; then
  echo 'var/.frozen is set (a migration is in progress); refusing to deploy' >&2
  exit 1
fi
# .env on disk is enough for docker compose itself (${VAR:?} substitution); this
# shell also needs PUBLIC_HOST, for the HTTPS check after a successful deploy (A9).
deploy/scripts/ensure-env.sh
set -a
# shellcheck disable=SC1091
source .env
set +a
target=$1
previous=$(cat var/.deployed-sha 2>/dev/null || true)
if [[ -n $previous && ! $previous =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Invalid var/.deployed-sha; refusing deploy' >&2
  exit 1
fi
export SHA="$target"

# A7: tag a deploy that exactly undoes the last recorded one as "rollback", so
# `make rollback` (rollback_target.py) can refuse to chain a second one back onto
# the broken image the first rollback just moved away from. The *last successful*
# ("deployed") entry is what matters, not the last line: an "already", "aborted"
# or "rolled_back" attempt in between must not hide it (rollback_target.py applies
# the same rule when computing what to roll back to).
via=deploy
if [[ -f var/state/ops/deploys.jsonl ]]; then
  last_previous=$(python3 -c '
import json, sys
last_previous = ""
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    if entry.get("result") == "deployed":
        last_previous = entry.get("previous", "")
print(last_previous)
' <var/state/ops/deploys.jsonl 2>/dev/null) || last_previous=
  [[ -n $last_previous && $last_previous == "$target" ]] && via=rollback
fi

# A tenant already degraded before this deploy must never block it, including pausing
# it (X10): only a tenant that becomes degraded *because of this deploy* does. Best
# effort: unreachable (e.g. the first deployment) counts as no pre-existing ones.
baseline_degraded=0
if response=$(curl --silent --show-error --fail --max-time 2 http://127.0.0.1:"${AUTOBOT_WEB_HOST_PORT:-8000}"/health/internal 2>/dev/null); then
  baseline_degraded=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tenants"]["degraded"])' \
    <<<"$response" 2>/dev/null) || baseline_degraded=0
fi

wait_health() {
  local deadline=$((SECONDS + 60)) response attempt
  for ((attempt=0; attempt<30 && SECONDS<deadline; attempt++)); do
    if response=$(curl --silent --show-error --fail --max-time 2 http://127.0.0.1:"${AUTOBOT_WEB_HOST_PORT:-8000}"/health/internal 2>/dev/null) && \
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
    curl --silent --show-error --fail --max-time 2 http://127.0.0.1:"${AUTOBOT_PANEL_HOST_PORT:-8080}"/healthz >/dev/null 2>&1 && return 0
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

# A9: `up` only recreates a container if its own definition changed, never because
# the content of a bind-mounted file did; reload Caddy by hand whenever its config
# did, instead of leaving it silently serving the previous one.
reload_caddy_if_changed() {
  local current previous_hash
  current=$(sha256sum deploy/caddy/Caddyfile | cut -d' ' -f1)
  previous_hash=$(cat var/.caddy-config-sha 2>/dev/null || true)
  if [[ $current != "$previous_hash" ]]; then
    # Only remembered once reloaded: a failed reload is retried on the next deploy.
    if "${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
      printf '%s' "$current" >var/.caddy-config-sha
    else
      echo 'Could not reload Caddy; it may still be running the previous config' >&2
    fi
  fi
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
  printf '{"at":"%s","sha":"%s","previous":"%s","result":"%s","via":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$target" "$previous" "$1" "$via" >>var/state/ops/deploys.jsonl
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

# A10: db and caddy are pinned by digest (S11), but nothing ever explicitly pulled
# them; `up` would only pull on first use, deep inside its own retry/error handling.
# Pulling them here catches a registry outage (or a cache that lost that digest)
# the same way the other images already do, instead of surfacing mid-`up`.
"${compose[@]}" pull db caddy || abort
# The first deployment needs PostgreSQL before a one-shot migration container.
"${compose[@]}" up -d --wait db || abort
"${compose[@]}" exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh || abort
"${compose[@]}" pull web worker-inbound worker-outbound panel || abort
# Logs are not critical: victorialogs never aborts or rolls back a deployment.
"${compose[@]}" pull victorialogs || echo 'Could not pull victorialogs; logs will be unavailable' >&2
"${compose[@]}" up -d victorialogs || echo 'Could not start victorialogs; logs will be unavailable' >&2

# A8: a dump right before a migration that will actually run something, so a bad one
# can be restored by hand; `abort`/`rollback` put the previous *code* back but never
# touch the schema a migration already changed. This is why migrations must only
# expand the schema (add, never remove/rename what the previous release still reads):
# a contract migration belongs to a later deploy, once rolling back to this one is
# no longer a concern.
if ! "${compose[@]}" run --rm web python manage.py migrate --check --noinput >/dev/null 2>&1; then
  echo 'Pending migrations: dumping the database before applying them' >&2
  mkdir -p var/backups
  # It holds every client's data: owner-only, like the other backups (umask 077).
  if (umask 077 && "${compose[@]}" exec -T db pg_dump -U postgres -d autobot -Fc \
    >var/backups/pre-migrate.dump.tmp); then
    mv var/backups/pre-migrate.dump.tmp var/backups/pre-migrate.dump || abort
  else
    abort
  fi
fi
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
    else
      reload_caddy_if_changed
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
reload_caddy_if_changed
printf '%s\n' "$target" >var/.deployed-sha.tmp
mv var/.deployed-sha.tmp var/.deployed-sha
record_deploy deployed
alert_ops deploy_ok "🟢 Desplegado ${target:0:7}" informational
# A9: never aborts or rolls back (DNS/certificate issuance can lag a first deploy,
# and reverting the image would not fix either); just makes sure an operator finds
# out if HTTPS stops answering. --resolve checks Caddy and its own certificate
# directly over loopback, without depending on DNS (which the external monitor
# already watches on its own); retried for up to a minute so a first deploy, where
# Caddy may still be requesting its certificate, doesn't report a false alarm.
if [[ -n ${PUBLIC_HOST:-} ]]; then
  https_ok=false
  https_deadline=$((SECONDS + ${AUTOBOT_HTTPS_CHECK_TIMEOUT:-60}))
  # L1 (localprod): Caddy's internal CA issues a certificate for `localhost` that
  # nothing trusts system-wide; production always keeps this unset and verifies
  # the real one.
  insecure=()
  [[ ${AUTOBOT_HTTPS_INSECURE:-false} == true ]] && insecure=(--insecure)
  while ((SECONDS < https_deadline)); do
    if curl --silent --show-error --fail --max-time 5 "${insecure[@]}" \
      --resolve "$PUBLIC_HOST:${AUTOBOT_CADDY_HTTPS_PORT:-443}:127.0.0.1" "https://$PUBLIC_HOST:${AUTOBOT_CADDY_HTTPS_PORT:-443}/health" >/dev/null 2>&1; then
      https_ok=true
      break
    fi
    sleep "${AUTOBOT_HTTPS_CHECK_INTERVAL:-5}"
  done
  if [[ $https_ok != true ]]; then
    echo 'HTTPS check failed after deploying; verify Caddy/TLS manually' >&2
    alert_ops deploy_https_check '🟡 HTTPS no respondió tras desplegar: revisar Caddy/TLS' informational
  fi
fi
echo "Deployed $target"
