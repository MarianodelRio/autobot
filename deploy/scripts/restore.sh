#!/usr/bin/env bash
# Restore a snapshot into this checkout on a fresh VPS or isolated local test.
# Requires a clean database volume; never overwrites an existing deployment.
set -euo pipefail
cd "$(dirname "$0")/../.."
umask 077
mkdir -p var
if [[ $# -ne 1 || $1 != --confirm-empty-target ]]; then
  echo 'Usage: deploy/scripts/restore.sh --confirm-empty-target' >&2
  exit 2
fi
project=${AUTOBOT_PROJECT:-autobot}
compose_base=${AUTOBOT_COMPOSE_BASE:-deploy/compose/compose.yaml}
compose_override=${AUTOBOT_COMPOSE_OVERRIDE:-deploy/compose/compose.prod.yaml}
if [[ -f var/.deployed-sha ]] || {
  docker volume inspect "${project}_pgdata" >/dev/null 2>&1 && [[ ! -f var/.restore-incomplete ]];
}; then
  echo 'Existing deployment/database volume; restore only on an empty target' >&2
  exit 1
fi
backup_config=${AUTOBOT_BACKUP_CONFIG:-/srv/autobot/var/backup.env}
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
"$restic_bin" restore latest --tag autobot --target "$stage"
# Restic restores paths relative to the root of the snapshot. Refuse incomplete backups.
for file in .env var/.deployed-sha var/google_sa.json deploy/caddy/Caddyfile var/backups/autobot.dump; do
  if [[ ! -s $stage/$file ]]; then
    echo "Missing from snapshot: $file" >&2
    exit 1
  fi
done
export SHA
SHA=$(cat "$stage/var/.deployed-sha")
if [[ ! $SHA =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Snapshot has no valid deployed SHA' >&2
  exit 1
fi
if [[ -f var/.restore-incomplete ]]; then
  if [[ $(cat var/.restore-incomplete) != "$SHA" ]]; then
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
printf '%s\n' "$SHA" >var/.restore-incomplete
mkdir -p var/backups
install -m 600 "$stage/.env" .env
install -m 600 "$stage/var/google_sa.json" var/google_sa.json
install -m 600 "$stage/deploy/caddy/Caddyfile" deploy/caddy/Caddyfile
docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" up -d --wait db
docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" exec -T db \
  sh -c 'PGPASSWORD="$FP_OWNER_PASSWORD" exec pg_restore -h 127.0.0.1 -U fp_owner -d autobot --clean --if-exists --no-owner --no-acl' \
  <"$stage/var/backups/autobot.dump"
# pg_restore --no-acl drops the GRANT/REVOKE state; reapply roles and permissions.
docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" exec -T db \
  bash /docker-entrypoint-initdb.d/init-roles.sh
docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" run --rm web \
  python manage.py apply_grants
if [[ ${AUTOBOT_RESTORE_DB_ONLY:-false} != true ]]; then
  docker compose --project-name "$project" -f "$compose_base" -f "$compose_override" up -d web worker caddy
fi
printf '%s\n' "$SHA" >var/.deployed-sha
rm -f var/.restore-incomplete
echo 'Restore completed; verify /health and per-tenant counts before DNS switch'
