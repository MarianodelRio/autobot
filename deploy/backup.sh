#!/usr/bin/env bash
# Run from the host timer as deploy; backup credentials live outside this repository.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
exec 9>.backup.lock
flock -n 9 || { echo 'Another backup is running' >&2; exit 1; }

backup_config=${AUTOBOT_BACKUP_CONFIG:-/srv/autobot/backup.env}
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

mkdir -p backups state/ops
dump_tmp=$(mktemp backups/.autobot.dump.XXXXXXXX)
dump_bytes=0

# Runs on every exit, success or failure: records the outcome for the panel (DESIGN
# §7.4) and never leaves the plaintext dump on disk once restic has it.
write_status() {
  local code=$? ok=false status_tmp
  [[ $code -eq 0 ]] && ok=true
  rm -f "$dump_tmp" backups/autobot.dump
  status_tmp=$(mktemp state/ops/.backup.json.XXXXXXXX)
  printf '{"finished_at":"%s","ok":%s,"dump_bytes":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$dump_bytes" >"$status_tmp"
  mv "$status_tmp" state/ops/backup.json
}
trap write_status EXIT

project=${AUTOBOT_PROJECT:-autobot}
compose_file=${AUTOBOT_COMPOSE_FILE:-compose.prod.yaml}
docker compose --project-name "$project" -f "$compose_file" exec -T db \
  pg_dump -U postgres -d autobot -Fc >"$dump_tmp"
test -s "$dump_tmp"
mv "$dump_tmp" backups/autobot.dump
dump_bytes=$(stat -c '%s' backups/autobot.dump)

"$restic_bin" backup --tag autobot backups/autobot.dump .env .deployed-sha \
  google_sa.json Caddyfile
# Group by tag: the dump path stays constant and all snapshots use the same policy.
"$restic_bin" forget --tag autobot --group-by tags --keep-daily 7 --keep-weekly 4 \
  --keep-monthly 6 --prune
python3 -c 'import os, urllib.request; urllib.request.urlopen(os.environ["HEALTHCHECKS_BACKUP_PING_URL"], timeout=10).close()'
echo 'Backup completed'
