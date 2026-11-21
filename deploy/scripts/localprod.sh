#!/usr/bin/env bash
# Reproduce production in local -- Caddy with TLS, `read_only` with the real
# UID, gunicorn, `deploy.sh`/`backup.sh`/`restore.sh` themselves -- in a disposable
# project (`autobot-localprod`) with its own ports, so it runs beside a normal
# `make up` without clashing with it. A local Docker registry stands in for GHCR.
#
# Usage: deploy/scripts/localprod.sh up|backup|restore|down
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)
# shellcheck source=./lib.sh
AUTOBOT_LIB_FUNCTIONS_ONLY=1 source "$root/deploy/scripts/lib.sh"
srv_dir=$root/var/localprod/srv
restic_dir=$root/var/localprod/restic
registry_name=autobot-localprod-registry
registry_port=5001
image_base=localhost:$registry_port

export AUTOBOT_PROJECT=autobot-localprod
export AUTOBOT_CADDY_HTTP_PORT=8081
export AUTOBOT_CADDY_HTTPS_PORT=8443
export AUTOBOT_WEB_HOST_PORT=18000
export AUTOBOT_PANEL_HOST_PORT=18080
export AUTOBOT_HTTPS_INSECURE=true
export RESTIC_BIN=${RESTIC_BIN:-restic}

# A real bug this drill found: compose.prod.yaml requires SHA (`${SHA:?...}`) for
# *every* command, `down` included; without it, `docker compose down` fails to
# interpolate the file and silently falls back to resolving the project from
# COMPOSE_PROJECT_NAME in --env-file (always "autobot": ensure-env.sh forces it),
# ignoring --project-name entirely -- which means it tears down the *regular dev
# stack* instead of localprod's. Always pass a real-looking SHA, never bare
# `docker compose ... down` against compose.prod.yaml.
compose_down() {
  local sha
  sha=$(cat "$srv_dir/var/.deployed-sha" 2>/dev/null || true)
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || sha=0000000000000000000000000000000000000000
  SHA="$sha" compose_in "$srv_dir" "$AUTOBOT_PROJECT" down -v
}

ensure_registry() {
  if ! docker inspect "$registry_name" >/dev/null 2>&1; then
    docker run -d --name "$registry_name" -p "127.0.0.1:$registry_port:5000" registry:2 >/dev/null
  elif [[ $(docker inspect -f '{{.State.Running}}' "$registry_name") != true ]]; then
    docker start "$registry_name" >/dev/null
  fi
}

# A plain copy, not a git worktree: localprod mirrors the current working tree
# exactly, uncommitted changes included, which is the point of trying something
# out before committing it.
sync_srv() {
  mkdir -p "$srv_dir"
  rsync -a --delete \
    --exclude /var/ --exclude /.git/ --exclude '**/__pycache__/' --exclude '**/.venv/' \
    --exclude '**/node_modules/' --exclude '**/dist/' \
    "$root/" "$srv_dir/"
}

build_and_push() {
  local sha=$1
  docker build -q -t "$image_base/autobot:$sha" -f "$root/apps/backend/Dockerfile" "$root/apps/backend" >/dev/null
  docker push -q "$image_base/autobot:$sha" >/dev/null
  docker build -q -t "$image_base/autobot-panel:$sha" "$root/apps/panel" >/dev/null
  docker push -q "$image_base/autobot-panel:$sha" >/dev/null
}

write_env() {
  local sha=$1
  umask 077
  : >"$srv_dir/.env"
  {
    printf 'ENVIRONMENT=prod\n'
    printf 'PUBLIC_HOST=localhost\n'
    printf 'AUTOBOT_IMAGE=%s/autobot\n' "$image_base"
    printf 'AUTOBOT_PANEL_IMAGE=%s/autobot-panel\n' "$image_base"
    printf 'DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n'
    # Defense in depth, like restore-test.sh: a real SHA= line here means a bare
    # `docker compose ...` run by hand against this .env still parses, so it never
    # falls back to resolving the project from --env-file's COMPOSE_PROJECT_NAME
    # (always "autobot") and colliding with the real dev stack.
    printf 'SHA=%s\n' "$sha"
  } >"$srv_dir/.env"
  mkdir -p "$srv_dir/var"
  [[ -s $srv_dir/var/google_sa.json ]] || printf '{}\n' >"$srv_dir/var/google_sa.json"
  chmod 600 "$srv_dir/var/google_sa.json"
  # Like bootstrap-server.sh on a real VPS: pre-create the bind-mount sources so
  # Docker never auto-creates them as root when a container starts before this
  # does -- a real bug this drill found: Caddy's own CA setup needs to write to
  # /data (var/state/caddy-data), and a root-owned directory refuses it.
  ensure_state_dirs "$srv_dir"
  (cd "$srv_dir" && deploy/scripts/ensure-env.sh)
}

cmd_up() {
  command -v rsync >/dev/null || { echo 'rsync is required' >&2; exit 1; }
  ensure_registry
  sync_srv
  local sha
  sha=$(printf 'localprod-%s' "$(date -u +%s)" | sha256sum | cut -c1-40)
  build_and_push "$sha"
  write_env "$sha"
  (cd "$srv_dir" && deploy/scripts/deploy.sh "$sha")
  echo "localprod is up: https://localhost:$AUTOBOT_CADDY_HTTPS_PORT/health (self-signed; curl -k)"
  echo "panel: http://127.0.0.1:$AUTOBOT_PANEL_HOST_PORT/healthz"
}

cmd_backup() {
  mkdir -p "$restic_dir"
  local config=$root/var/localprod/backup.env
  if [[ ! -f $config ]]; then
    printf 'password-only-for-localprod\n' >"$root/var/localprod/restic-password"
    chmod 600 "$root/var/localprod/restic-password"
    cat >"$config" <<EOF
RESTIC_REPOSITORY=$restic_dir
RESTIC_PASSWORD_FILE=$root/var/localprod/restic-password
HEALTHCHECKS_BACKUP_PING_URL=http://127.0.0.1:0/localprod-no-ping
EOF
    chmod 600 "$config"
  fi
  if ! AUTOBOT_BACKUP_CONFIG="$config" "$RESTIC_BIN" \
    --repo "$restic_dir" --password-file "$root/var/localprod/restic-password" cat config >/dev/null 2>&1; then
    "$RESTIC_BIN" --repo "$restic_dir" --password-file "$root/var/localprod/restic-password" init
  fi
  # The ping URL points nowhere on purpose (no real healthchecks.io account for a
  # local drill); let backup.sh's own ping failure not fail the whole backup.
  (cd "$srv_dir" && AUTOBOT_BACKUP_CONFIG="$config" deploy/scripts/backup.sh) || {
    echo 'backup.sh failed (check above; a failed ping to the dummy URL is expected and ignorable)' >&2
  }
}

cmd_restore() {
  read -r -p "This wipes localprod's database volume and replays the last backup. Continue? [y/N] " confirm
  [[ $confirm == y ]] || exit 1
  compose_down
  rm -f "$srv_dir/var/.deployed-sha"
  # This machine is not a bootstrapped VM and never will be: say so out loud instead
  # of faking /var/lib/autobot/bootstrap-complete (only install-vm.sh writes it).
  (cd "$srv_dir" && AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true \
    AUTOBOT_BACKUP_CONFIG="$root/var/localprod/backup.env" \
    deploy/scripts/restore.sh --confirm-empty-target)
}

cmd_down() {
  if [[ -d $srv_dir && -f $srv_dir/.env ]]; then
    compose_down || true
  fi
  docker rm -f "$registry_name" >/dev/null 2>&1 || true
}

case ${1:-} in
up) cmd_up ;;
backup) cmd_backup ;;
restore) cmd_restore ;;
down) cmd_down ;;
*)
  echo 'Usage: deploy/scripts/localprod.sh up|backup|restore|down' >&2
  exit 2
  ;;
esac
