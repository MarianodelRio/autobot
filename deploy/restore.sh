#!/usr/bin/env bash
# Restore a snapshot into this checkout on a fresh VPS or isolated local test.
# Requires a clean database volume; never overwrites an existing deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
if [[ $# -ne 1 || $1 != --confirm-empty-target ]]; then
  echo 'Usage: deploy/restore.sh --confirm-empty-target' >&2
  exit 2
fi
project=${FLOWPILOT_PROJECT:-flowpilot}
compose_file=${FLOWPILOT_COMPOSE_FILE:-compose.prod.yaml}
if [[ -f .deployed-sha ]] || {
  docker volume inspect "${project}_pgdata" >/dev/null 2>&1 && [[ ! -f .restore-incomplete ]];
}; then
  echo 'Existing deployment/database volume; restore only on an empty target' >&2
  exit 1
fi
backup_config=${FLOWPILOT_BACKUP_CONFIG:-/srv/flowpilot/backup.env}
if [[ ! -f $backup_config ]]; then
  echo 'Backup configuration is missing' >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$backup_config"
: "${RESTIC_REPOSITORY:?}"
: "${RESTIC_PASSWORD_FILE:?}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
restic_bin=${RESTIC_BIN:-restic}

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
"$restic_bin" restore latest --tag flowpilot --target "$stage"
# Restic restores paths relative to the root of the snapshot. Refuse incomplete backups.
for file in .env .deployed-sha secrets.yaml google_sa.json Caddyfile backups/flowpilot.dump; do
  if [[ ! -s $stage/$file ]]; then
    echo "Missing from snapshot: $file" >&2
    exit 1
  fi
done
export SHA
SHA=$(cat "$stage/.deployed-sha")
if [[ ! $SHA =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Snapshot has no valid deployed SHA' >&2
  exit 1
fi
if [[ -f .restore-incomplete ]]; then
  if [[ $(cat .restore-incomplete) != "$SHA" ]]; then
    echo 'Partial restore is for another SHA; refusing to mix snapshots' >&2
    exit 1
  fi
  # A failed start can leave services running. Never run pg_restore --clean
  # while web or worker might still be using the database.
  for service in web worker caddy; do
    containers=$(docker ps -q --filter "label=com.docker.compose.project=$project" \
      --filter "label=com.docker.compose.service=$service") || {
        echo 'Could not enumerate running services; refusing restore' >&2
        exit 1
      }
    while read -r container; do
      [[ -z $container ]] || docker stop "$container" >/dev/null
    done <<<"$containers"
  done
fi
printf '%s\n' "$SHA" >.restore-incomplete
for file in .env secrets.yaml google_sa.json Caddyfile; do
  install -m 600 "$stage/$file" "$file"
done
docker compose --project-name "$project" -f "$compose_file" up -d --wait db
docker compose --project-name "$project" -f "$compose_file" exec -T db \
  sh -c 'PGPASSWORD="$FP_OWNER_PASSWORD" exec pg_restore -h 127.0.0.1 -U fp_owner -d flowpilot --clean --if-exists --no-owner --no-acl' \
  <"$stage/backups/flowpilot.dump"
if [[ ${FLOWPILOT_RESTORE_DB_ONLY:-false} != true ]]; then
  docker compose --project-name "$project" -f "$compose_file" up -d web worker caddy
fi
printf '%s\n' "$SHA" >.deployed-sha
rm -f .restore-incomplete
echo 'Restore completed; verify /health and per-tenant counts before DNS switch'
