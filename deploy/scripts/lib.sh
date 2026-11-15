#!/usr/bin/env bash
# shellcheck disable=SC2034  # compose is for the scripts that source this file.
# Sourced by every production script (deploy, backup, restore, manage, compose):
# the repo root, project name and `docker compose` command, defined once (A1).
# Without `--env-file`, compose looks for `.env` next to the *first* `-f` file
# (deploy/compose/), not the caller's directory, so the root `.env` is silently
# ignored; every script that forgot this flag read no configuration from it.
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root" || exit
project=${AUTOBOT_PROJECT:-autobot}
compose_base=${AUTOBOT_COMPOSE_BASE:-$root/deploy/compose/compose.yaml}
compose_override=${AUTOBOT_COMPOSE_OVERRIDE:-$root/deploy/compose/compose.prod.yaml}

# A2: compose.prod.yaml requires SHA for every command, even `exec`/`logs`, which
# don't touch an image. Default it from the last deploy so only deploy.sh and
# restore.sh (which know a different, specific SHA) need to set it themselves.
if [[ -z ${SHA:-} && -f $root/var/.deployed-sha ]]; then
  SHA=$(cat "$root/var/.deployed-sha")
fi
export SHA

compose=(docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" --env-file "$root/.env")
