#!/usr/bin/env bash
# Run from the host timer as deploy (A11): every deploy leaves the previous image
# behind (needed for an instant rollback) and dangling layers from failed pulls;
# left unchecked, the 40 GB disk a small VPS has fills up over time.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p var

# Share deploy.sh's lock (read-only probe): a prune running at the exact moment a
# deploy pulls a new image could otherwise race it; a shared lock only ever blocks
# against deploy.sh's exclusive one, never against another prune.
exec 9>var/.deploy.lock
flock -s -w "${AUTOBOT_PRUNE_LOCK_WAIT:-60}" 9 || {
  echo 'A deployment is running; skipping this prune' >&2
  exit 0
}

# Keeps anything still referenced by a container and anything pulled in the last
# day, so a deploy in progress is never affected. An older, unreferenced image
# (the previous SHA's, once it's no longer the one running) is removed; a rollback
# past that point re-pulls it, same as any other image `up` doesn't find locally.
docker image prune --all --force --filter 'until=24h'

# A8: var/backups/pre-migrate.dump holds every client's data in the clear and is
# never included in the restic backup on purpose; it must not outlive the window
# where rolling back to the deploy that made it is still plausible.
find var/backups/pre-migrate.dump -maxdepth 0 -mtime +7 -delete 2>/dev/null || true
