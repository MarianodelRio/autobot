#!/usr/bin/env bash
# Move the whole deployment to another VPS (`make server-migrate FROM= TO=`),
# run from the operator's machine. FROM and TO are SSH-reachable hosts (already
# resolvable, e.g. via ~/.ssh/config aliases); TO must be a fresh machine. The only
# thing it reads from var/server.env (deploy/env/server.env.example) is PUBLIC_HOST,
# for the health check through the new machine; images, Google service account and
# restic destination travel with the backed-up .env, so the same domain and backup
# repository are kept and only the machine changes. The one thing that does NOT travel in
# the backup is SECRETS_ENCRYPTION_KEY (ADR-021): copy it from where it is kept to TO first,
# as a mode-0600 file (default /srv/autobot/var/secrets-key, or AUTOBOT_MIGRATE_SECRETS_KEY_FILE
# for another path on TO); restore.sh reads it from there, and it can be deleted afterwards
# (the restored .env keeps it).
#
# TO must have been prepared with `install-vm.sh --restore-target` (ADR-017) run on
# that VM: users, Docker, timers, SSH hardening and the bootstrap marker, but no
# .env, no deploy and no workers. Its own CI deploy key (printed by that script)
# replaces the one of FROM in GitHub at the `finish` step.
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

# Where, on TO, restore.sh finds the encryption key (it is not inside the snapshot).
secrets_key_file=${AUTOBOT_MIGRATE_SECRETS_KEY_FILE:-/srv/autobot/var/secrets-key}

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

# FROM and TO can be aliases of the same machine (an alias in ~/.ssh/config, an IP,
# a DNS name): comparing the strings is not enough, so also compare /etc/machine-id.
# Everything destructive below (`down -v` on TO) is only safe if TO is really another
# machine and has never been deployed to.
if [[ $from == "$to" ]]; then
  echo 'FROM and TO are the same host; refusing' >&2
  exit 2
fi
guard_distinct_hosts() {
  local from_id to_id
  from_id=$(ssh_deploy "$from" 'cat /etc/machine-id') || { echo "Cannot reach FROM ($from)" >&2; return 1; }
  to_id=$(ssh_deploy "$to" 'cat /etc/machine-id') || { echo "Cannot reach TO ($to)" >&2; return 1; }
  if [[ -z $from_id || $from_id == "$to_id" ]]; then
    echo "FROM and TO are the same machine (same machine-id); refusing" >&2
    return 1
  fi
}
# TO must be an empty target: no recorded deployment and no application container
# running. A rehearsal restores into it and then `down -v` wipes its database volume,
# which on a deployed machine would destroy the live database.
# Ids of the application containers running on a host. One `docker ps` per service: repeated
# `--filter label=...service=X` filters are ANDed by Docker (a container has one service
# label), so a single command with all of them would match nothing and the guards below
# would never fire.
# shellcheck disable=SC2016  # intentional: $s expands on the remote host, not here.
app_containers_cmd='for s in web web-panel worker-inbound worker-calendar worker-periodic worker-outbound; do docker ps -q --filter label=com.docker.compose.project=autobot --filter label=com.docker.compose.service=$s; done'

guard_empty_target() {
  if ssh_deploy "$to" 'test -f /srv/autobot/var/.deployed-sha'; then
    echo "TO ($to) already has a deployment (var/.deployed-sha); refusing to touch its volumes" >&2
    return 1
  fi
  local running
  running=$(ssh_deploy "$to" \
    "$app_containers_cmd")
  if [[ -n $running ]]; then
    echo "TO ($to) has application containers running; refusing to touch its volumes" >&2
    return 1
  fi
}

# Step 2+3: TO must already be installed (install-vm.sh --restore-target, run on
# TO) before this runs. This step only rehearses the restore (never marks TO as deployed: restore.sh skips that when
# AUTOBOT_RESTORE_DB_ONLY=true) and compares per-tenant counts.
step_rehearse() {
  guard_distinct_hosts
  guard_empty_target
  ssh_deploy "$to" "test -s $secrets_key_file" || {
    echo "TO has no encryption key at $secrets_key_file (it never travels in the backup, ADR-021): copy it there, mode 0600, and retry" >&2
    return 1
  }
  # restore.sh installs the snapshot's .env and runs ensure-env.sh itself.
  ssh_deploy "$to" "AUTOBOT_SECRETS_KEY_FILE=$secrets_key_file AUTOBOT_RESTORE_DB_ONLY=true /srv/autobot/deploy/scripts/restore.sh --confirm-empty-target"
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
  # Checked again right before the destructive part, not just at the start.
  guard_empty_target
  ssh_deploy "$to" 'SHA=0000000000000000000000000000000000000000 /srv/autobot/deploy/scripts/compose.sh down -v'
}

# Step 4: freeze and do the final backup on FROM.
step_freeze() {
  guard_distinct_hosts
  confirm "Freeze $from and stop it for the cutover? Real traffic stops here." || return 1
  ssh_deploy "$from" 'touch /srv/autobot/var/.frozen'
  if command -v gh >/dev/null 2>&1; then
    gh workflow disable deploy.yml || echo 'Could not disable deploy.yml; disable it by hand' >&2
  fi
  ssh_admin "$from" 'sudo systemctl stop autobot-backup.timer'
  ssh_deploy "$from" '/srv/autobot/deploy/scripts/compose.sh stop worker-inbound worker-calendar worker-periodic worker-outbound web web-panel panel caddy'
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
    "AUTOBOT_SECRETS_KEY_FILE=$secrets_key_file AUTOBOT_RESTORE_SNAPSHOT=$snapshot /srv/autobot/deploy/scripts/restore.sh --confirm-empty-target"
  ssh_deploy "$to" "curl --silent --show-error --fail --max-time 5 --resolve '$PUBLIC_HOST:443:127.0.0.1' https://$PUBLIC_HOST/health"
  echo 'TO answers on HTTPS without the workers running. Verify it by hand, then:'
}

step_start_destination() {
  # Never start sending from TO while FROM might still have an app container
  # up: a real double-send would duplicate outbound messages.
  running=$(ssh_deploy "$from" \
    "$app_containers_cmd")
  if [[ -n $running ]]; then
    echo "FROM ($from) still has application containers running; refusing to start TO's workers" >&2
    return 1
  fi
  confirm "FROM has no application containers running. Start TO's workers now?" || return 1
  ssh_deploy "$to" '/srv/autobot/deploy/scripts/compose.sh up -d worker-inbound worker-calendar worker-periodic worker-outbound'
  echo 'TO is now live. Change the DNS for '"$PUBLIC_HOST"' to TO, then --only=finish.'
}

step_finish() {
  if command -v gh >/dev/null 2>&1; then
    gh secret set DEPLOY_HOST --env production --body "$to"
    ssh-keyscan -H "$to" | gh secret set DEPLOY_KNOWN_HOSTS --env production
    # TO generated its own CI key (install-vm.sh): the one in GitHub still belongs
    # to FROM and would be rejected by TO.
    if ssh_admin "$to" 'sudo test -f /root/autobot-ci-deploy-key'; then
      ssh_admin "$to" 'sudo cat /root/autobot-ci-deploy-key' | gh secret set DEPLOY_SSH_KEY --env production
      ssh_admin "$to" 'sudo shred -u /root/autobot-ci-deploy-key'
    else
      echo "TO's CI key file (/root/autobot-ci-deploy-key) is gone: rerun 'install-vm.sh --only ci-key --rotate-ci-key' on TO and set DEPLOY_SSH_KEY by hand" >&2
    fi
    gh workflow enable deploy.yml
  else
    echo 'gh not found; update DEPLOY_HOST/DEPLOY_KNOWN_HOSTS/DEPLOY_SSH_KEY and re-enable deploy.yml by hand' >&2
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
