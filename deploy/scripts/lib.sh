#!/usr/bin/env bash
# shellcheck disable=SC2034  # compose is for the scripts that source this file.
# Sourced by every production script (deploy, backup, restore, manage, compose):
# the repo root, project name and `docker compose` command, defined once.
# Without `--env-file`, compose looks for `.env` next to the *first* `-f` file
# (deploy/compose/), not the caller's directory, so the root `.env` is silently
# ignored; every script that forgot this flag read no configuration from it.
# Every script that sources this file runs as the deploy user; as root,
# DEPLOY_UID would resolve to 0 (ensure-env.sh refuses that too, but only once it
# runs, already past lib.sh's own setup) and every container would run as root.
# Helpers for the local drills (localprod.sh, restore-test.sh), which run a copy of the
# checkout in another directory. They source this file with AUTOBOT_LIB_FUNCTIONS_ONLY=1
# to get just the functions, without the root check, the `cd` or the SHA default below.
#
# compose_in DIR PROJECT ARGS...: `docker compose` for the production files of the
# checkout in DIR, with its own .env (relative to DIR, not to deploy/compose/).
compose_in() {
  local dir=$1 project=$2
  shift 2
  (cd "$dir" && docker compose --project-name "$project" \
    -f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml --env-file .env "$@")
}

# ensure_state_dirs DIR: the bind-mount sources under DIR/var/state, created by the
# caller so Docker never auto-creates them as root when a container starts first.
ensure_state_dirs() {
  mkdir -p "$1/var/state/ops" "$1/var/state/caddy-data" "$1/var/state/caddy-config"
}

if [[ ${AUTOBOT_LIB_FUNCTIONS_ONLY:-} == 1 ]]; then
  return 0
fi

if [[ $(id -u) == 0 ]]; then
  echo 'Do not run this as root; run as the deploy user' >&2
  exit 1
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root" || exit
project=${AUTOBOT_PROJECT:-autobot}
compose_base=${AUTOBOT_COMPOSE_BASE:-$root/deploy/compose/compose.yaml}
compose_override=${AUTOBOT_COMPOSE_OVERRIDE:-$root/deploy/compose/compose.prod.yaml}

# compose.prod.yaml requires SHA for every command, even `exec`/`logs`, which
# don't touch an image. Default it from the last deploy so only deploy.sh and
# restore.sh (which know a different, specific SHA) need to set it themselves.
if [[ -z ${SHA:-} && -f $root/var/.deployed-sha ]]; then
  SHA=$(cat "$root/var/.deployed-sha")
fi
export SHA

compose=(docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" --env-file "$root/.env")
