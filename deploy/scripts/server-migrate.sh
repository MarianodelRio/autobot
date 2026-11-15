#!/usr/bin/env bash
# Move the whole deployment to another VPS (T4, `make server-migrate FROM= TO=`),
# run from the operator's machine. FROM and TO are SSH-reachable hosts (already
# resolvable, e.g. via ~/.ssh/config aliases); TO must be a fresh machine. Shared
# config (images, PUBLIC_HOST, Google service account, restic destination) comes
# from var/server.env (deploy/env/server.env.example) -- the same domain and
# backup repository are kept, only the machine changes.
#
# Idempotent per step; every destructive or externally-visible step asks for
# confirmation first (CLAUDE.md: infrastructure changes need explicit approval).
# `--only=STEP` re-runs one step (useful after fixing something mid-migration).
#
# Usage: deploy/scripts/server-migrate.sh FROM TO [--only=STEP]
#   STEP one of: rehearse, freeze, cutover, start-destination, finish
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ $# -lt 2 ]]; then
  echo 'Usage: deploy/scripts/server-migrate.sh FROM TO [--only=STEP]' >&2
  exit 2
fi
from=$1
to=$2
shift 2
only=${1:-}
only=${only#--only=}

server_env=${AUTOBOT_SERVER_ENV:-var/server.env}
if [[ ! -f $server_env ]]; then
  echo "$server_env is missing; copy deploy/env/server.env.example and fill it in" >&2
  exit 1
fi
set -a
# shellcheck source=/dev/null
source "$server_env"
set +a
: "${PUBLIC_HOST:?Set PUBLIC_HOST in $server_env}"

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
# shellcheck disable=SC2029  # intentional: every caller's command string is meant
# to expand locally (sha, snapshot id, counts_sql...) before reaching the remote shell.
ssh_deploy() { local host=$1; shift; ssh "${ssh_opts[@]}" "deploy@$host" "$@"; }
# shellcheck disable=SC2029
ssh_admin() { local host=$1; shift; ssh "${ssh_opts[@]}" "admin@$host" "$@"; }

confirm() {
  read -r -p "$1 [y/N] " reply </dev/tty
  [[ $reply == y || $reply == Y ]]
}

# Step 2+3: TO must already be bootstrapped (server-init.sh --only=base/harden-ssh/
# secrets, with var/server.env pointed at it) before this runs. This step only
# rehearses the restore (never marks TO as deployed: restore.sh skips that when
# AUTOBOT_RESTORE_DB_ONLY=true) and compares per-tenant counts.
step_rehearse() {
  # restore.sh installs the snapshot's .env and runs ensure-env.sh itself.
  ssh_deploy "$to" 'AUTOBOT_RESTORE_DB_ONLY=true /srv/autobot/deploy/scripts/restore.sh --confirm-empty-target'
  # Via `db`'s own postgres superuser, like restore-test.sh: RLS would otherwise
  # hide everything from fp_app without a tenant context set.
  local counts_sql="SELECT t.slug, count(c.id) FROM tenant t LEFT JOIN contact c ON c.tenant_id=t.id GROUP BY t.slug ORDER BY t.slug"
  echo '--- counts on FROM ---'
  ssh_deploy "$from" "/srv/autobot/deploy/scripts/compose.sh exec -T db psql -U postgres -d autobot -At -c \"$counts_sql\""
  echo '--- counts on TO (rehearsal) ---'
  ssh_deploy "$to" "SHA=0000000000000000000000000000000000000000 /srv/autobot/deploy/scripts/compose.sh exec -T db psql -U postgres -d autobot -At -c \"$counts_sql\""
  echo 'Compare the two tables above by hand before continuing.'
  # DB_ONLY never wrote var/.deployed-sha, so compose.prod.yaml's ${SHA:?} has
  # nothing to read; `down` never uses the image, so any well-formed value does.
  ssh_deploy "$to" 'SHA=0000000000000000000000000000000000000000 /srv/autobot/deploy/scripts/compose.sh down -v'
}

# Step 4: freeze and do the final backup on FROM.
step_freeze() {
  confirm "Freeze $from and stop it for the cutover? Real traffic stops here." || return 1
  ssh_deploy "$from" 'touch /srv/autobot/var/.frozen'
  if command -v gh >/dev/null 2>&1; then
    gh workflow disable deploy.yml || echo 'Could not disable deploy.yml; disable it by hand' >&2
  fi
  ssh_admin "$from" 'sudo systemctl stop autobot-backup.timer'
  ssh_deploy "$from" '/srv/autobot/deploy/scripts/compose.sh stop worker-inbound worker-outbound web panel caddy'
  ssh_deploy "$from" '/srv/autobot/deploy/scripts/backup.sh'
  # shellcheck disable=SC2016  # intentional: expands remotely inside the ssh'd shell, not here.
  snapshot=$(ssh_deploy "$from" \
    'AUTOBOT_BACKUP_CONFIG=/srv/autobot/var/backup.env bash -c "set -a; . \"$AUTOBOT_BACKUP_CONFIG\"; restic snapshots --tag autobot --latest 1 --json"' \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["short_id"])')
  printf '%s\n' "$snapshot" >var/.server-migrate-snapshot
  echo "Final snapshot: $snapshot (saved to var/.server-migrate-snapshot)"
}

# Step 5+6: restore that exact snapshot on TO and bring it up without the workers.
step_cutover() {
  local snapshot
  snapshot=$(cat var/.server-migrate-snapshot 2>/dev/null) || {
    echo 'var/.server-migrate-snapshot missing; run --only=freeze first' >&2
    return 1
  }
  ssh_deploy "$to" \
    "AUTOBOT_RESTORE_SNAPSHOT=$snapshot /srv/autobot/deploy/scripts/restore.sh --confirm-empty-target"
  ssh_deploy "$to" "curl --silent --show-error --fail --max-time 5 --resolve '$PUBLIC_HOST:443:127.0.0.1' https://$PUBLIC_HOST/health"
  echo 'TO answers on HTTPS without the workers running. Verify it by hand, then:'
}

step_start_destination() {
  # Never start sending from TO while FROM might still have an app container
  # up: a real double-send would duplicate outbound messages.
  running=$(ssh_deploy "$from" \
    "docker ps -q --filter label=com.docker.compose.project=autobot --filter label=com.docker.compose.service=web --filter label=com.docker.compose.service=worker-inbound --filter label=com.docker.compose.service=worker-outbound")
  if [[ -n $running ]]; then
    echo "FROM ($from) still has application containers running; refusing to start TO's workers" >&2
    return 1
  fi
  confirm "FROM has no application containers running. Start TO's workers now?" || return 1
  ssh_deploy "$to" '/srv/autobot/deploy/scripts/compose.sh up -d worker-inbound worker-outbound'
  echo 'TO is now live. Change the DNS for '"$PUBLIC_HOST"' to TO, then --only=finish.'
}

step_finish() {
  if command -v gh >/dev/null 2>&1; then
    gh secret set DEPLOY_HOST --env production --body "$to"
    ssh-keyscan -H "$to" | gh secret set DEPLOY_KNOWN_HOSTS --env production
    gh workflow enable deploy.yml
  else
    echo 'gh not found; update DEPLOY_HOST/DEPLOY_KNOWN_HOSTS and re-enable deploy.yml by hand' >&2
  fi
  ssh_admin "$to" 'sudo systemctl start autobot-backup.timer'
  echo "FROM ($from) stays frozen (var/.frozen) and stopped; keep it for 7 days, then decommission it."
}

run() {
  local name=$1 fn=$2
  [[ -z $only || $only == "$name" ]] || return 0
  echo "== $name =="
  "$fn"
}

run rehearse step_rehearse
run freeze step_freeze
run cutover step_cutover
run start-destination step_start_destination
run finish step_finish
echo 'server-migrate.sh finished'
