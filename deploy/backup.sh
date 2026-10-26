#!/usr/bin/env bash
# Run from the host timer as deploy; backup credentials live outside this repository.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
exec 9>.backup.lock
flock -n 9 || { echo 'Another backup is running' >&2; exit 1; }

backup_config=${FLOWPILOT_BACKUP_CONFIG:-/srv/flowpilot/backup.env}
if [[ ! -f $backup_config ]]; then
  echo 'Backup configuration is missing' >&2
  exit 1
fi
# This file is owned by deploy with mode 0600 and contains RESTIC_REPOSITORY,
# RESTIC_PASSWORD_FILE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and ping URL.
# shellcheck source=/dev/null
source "$backup_config"
: "${RESTIC_REPOSITORY:?}"
: "${RESTIC_PASSWORD_FILE:?}"
: "${HEALTHCHECKS_BACKUP_PING_URL:?}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export HEALTHCHECKS_BACKUP_PING_URL
restic_bin=${RESTIC_BIN:-restic}

mkdir -p backups
dump_tmp=$(mktemp backups/.flowpilot.dump.XXXXXXXX)
trap 'rm -f "$dump_tmp"' EXIT
project=${FLOWPILOT_PROJECT:-flowpilot}
compose_file=${FLOWPILOT_COMPOSE_FILE:-compose.prod.yaml}
docker compose --project-name "$project" -f "$compose_file" exec -T db \
  pg_dump -U postgres -d flowpilot -Fc >"$dump_tmp"
test -s "$dump_tmp"
mv "$dump_tmp" backups/flowpilot.dump
trap 'rm -f backups/flowpilot.dump' EXIT

"$restic_bin" backup --tag flowpilot backups/flowpilot.dump .env .deployed-sha \
  secrets.yaml google_sa.json Caddyfile
# Group by tag: the dump path stays constant and all snapshots use the same policy.
"$restic_bin" forget --tag flowpilot --group-by tags --keep-daily 7 --keep-weekly 4 \
  --keep-monthly 6 --prune
python3 -c 'import os, urllib.request; urllib.request.urlopen(os.environ["HEALTHCHECKS_BACKUP_PING_URL"], timeout=10).close()'
echo 'Backup completed'
