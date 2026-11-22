#!/usr/bin/env bash
# Restore a snapshot into this checkout on a fresh VPS or isolated local test.
# Requires a clean database volume; never overwrites an existing deployment.
set -euo pipefail
# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
umask 077
mkdir -p var
if [[ $# -ne 1 || $1 != --confirm-empty-target ]]; then
  echo 'Usage: deploy/scripts/restore.sh --confirm-empty-target' >&2
  exit 2
fi
# a target that was never bootstrapped is missing the deploy user, the pinned
# UFW/SSH hardening and the systemd timers; restoring onto it would silently skip
# all of that instead of failing loudly. The marker is written by install-vm.sh
# (ADR-017) once the base install and the SSH hardening are done; nothing else
# creates it. AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true exists only for drills on a
# machine that is not a VM (restore-test.sh, localprod.sh): it skips the check out
# loud instead of faking the marker.
bootstrap_marker=${AUTOBOT_BOOTSTRAP_MARKER:-/var/lib/autobot/bootstrap-complete}
if [[ ${AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK:-false} == true ]]; then
  echo "Skipping the bootstrap check (AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true): drill only" >&2
elif [[ ! -f $bootstrap_marker ]]; then
  echo "Bootstrap not done ($bootstrap_marker missing); run deploy/scripts/install-vm.sh first" >&2
  exit 1
fi
# server-migrate.sh freezes the origin before its final backup; a target that
# is itself frozen (e.g. being migrated away from) must not be restored into either.
if [[ -f var/.frozen ]]; then
  echo 'var/.frozen is set (a migration is in progress); refusing to restore' >&2
  exit 1
fi
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
# server-migrate.sh always passes a specific snapshot id (never "latest"), so
# the destination restores exactly the snapshot taken at the origin's cutover,
# not whatever newer snapshot a still-running source (or another target) wrote
# in the meantime.
# --no-lock (honoured by `restore`, unlike `backup`): the credential on a new server may
# be read-only and could not delete a lock file afterwards (ADR-021).
"$restic_bin" --no-lock restore "${AUTOBOT_RESTORE_SNAPSHOT:-latest}" --tag autobot --target "$stage"
# Restic restores paths relative to the root of the snapshot. Refuse incomplete backups.
for file in var/.deployed-sha var/google_sa.json deploy/caddy/Caddyfile var/backups/autobot.dump; do
  if [[ ! -s $stage/$file ]]; then
    echo "Missing from snapshot: $file" >&2
    exit 1
  fi
done
# The snapshot's .env has no SECRETS_ENCRYPTION_KEY since ADR-021 (backup.sh strips it so
# the key never travels with the data it decrypts): it is staged as var/backups/autobot.env
# and the key must be given here, explicitly, from where the operator keeps it, either as
# AUTOBOT_SECRETS_KEY_FILE=<file whose first line is the key> or as SECRETS_ENCRYPTION_KEY
# in the environment. Snapshots older than that carry the whole .env (legacy): their own
# key is used, with a warning. Checked before touching anything on this machine.
env_snapshot=$stage/var/backups/autobot.env
secrets_key=${SECRETS_ENCRYPTION_KEY:-}
if [[ -z $secrets_key && -n ${AUTOBOT_SECRETS_KEY_FILE:-} ]]; then
  if [[ ! -r $AUTOBOT_SECRETS_KEY_FILE ]]; then
    echo "AUTOBOT_SECRETS_KEY_FILE ($AUTOBOT_SECRETS_KEY_FILE) is not a readable file" >&2
    exit 1
  fi
  secrets_key=$(head -n 1 "$AUTOBOT_SECRETS_KEY_FILE" | tr -d '[:space:]')
fi
if [[ -s $env_snapshot ]]; then
  if [[ -z $secrets_key ]]; then
    echo 'The snapshot does not contain SECRETS_ENCRYPTION_KEY (by design). Give the key explicitly: AUTOBOT_SECRETS_KEY_FILE=<file with the key> or SECRETS_ENCRYPTION_KEY=<key>; without it the restored channel secrets cannot be decrypted' >&2
    exit 1
  fi
elif [[ -s $stage/.env ]]; then
  env_snapshot=$stage/.env
  if [[ -z $secrets_key ]]; then
    secrets_key=$(sed -n 's/^SECRETS_ENCRYPTION_KEY=//p' "$env_snapshot" | head -n 1)
  fi
  echo 'Legacy snapshot: its .env carries SECRETS_ENCRYPTION_KEY (taken before ADR-021)' >&2
  if [[ -z $secrets_key ]]; then
    echo 'The snapshot has no .env with SECRETS_ENCRYPTION_KEY and none was given' >&2
    exit 1
  fi
else
  echo 'Missing from snapshot: var/backups/autobot.env (or a legacy .env)' >&2
  exit 1
fi
# SECRETS_ENCRYPTION_KEY may hold several comma-separated keys (rotar-secretos.md): each must be valid.
if ! python3 -c 'import base64, sys
for key in sys.argv[1].split(","):
    assert len(base64.urlsafe_b64decode(key.strip())) == 32' "$secrets_key" 2>/dev/null; then
  echo 'SECRETS_ENCRYPTION_KEY is not a valid Fernet key (44 characters of url-safe base64; several may be separated by commas)' >&2
  exit 1
fi
export SHA
SHA=$(cat "$stage/var/.deployed-sha")
if [[ ! $SHA =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Snapshot has no valid deployed SHA' >&2
  exit 1
fi
# match the code to the data being restored, same as a normal deploy does.
if [[ -d .git ]] && ! git checkout --quiet --detach "$SHA"; then
  echo 'Could not checkout the snapshot SHA' >&2
  exit 1
fi
if [[ -f var/.restore-incomplete ]]; then
  if [[ $(cat var/.restore-incomplete) != "$SHA" ]]; then
    echo 'Partial restore is for another SHA; refusing to mix snapshots' >&2
    exit 1
  fi
  # A failed start can leave services running. Never run pg_restore --clean
  # while web or worker might still be using the database.
  for service in web web-panel worker-inbound worker-outbound panel caddy; do
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
install -m 600 "$env_snapshot" .env
# Whatever key line the snapshot had is replaced by the one the operator gave: ensure-env.sh
# would otherwise generate a NEW key for a .env without one, and every secret would be lost.
sed -i -E '/^[[:space:]]*(export[[:space:]]+)?SECRETS_ENCRYPTION_KEY=/d' .env
printf 'SECRETS_ENCRYPTION_KEY=%s\n' "$secrets_key" >>.env
install -m 600 "$stage/var/google_sa.json" var/google_sa.json
install -m 600 "$stage/deploy/caddy/Caddyfile" deploy/caddy/Caddyfile
# Caddy's own state and the deploy log, both optional (backup.sh only includes
# them if they existed on the source). Restoring certificates avoids reissuing them
# from scratch; without the state Caddy just requests new ones on first start.
for optional_path in var/state/caddy-data var/state/caddy-config; do
  if [[ -e $stage/$optional_path ]]; then
    mkdir -p var/state
    rm -rf "$optional_path"
    cp -a "$stage/$optional_path" "$optional_path"
  fi
done
if [[ -s $stage/var/state/ops/deploys.jsonl ]]; then
  mkdir -p var/state/ops
  install -m 600 "$stage/var/state/ops/deploys.jsonl" var/state/ops/deploys.jsonl
fi
# the restored .env carries the uid of whichever host it was backed up from;
# ensure-env.sh re-derives DEPLOY_UID for this one.
deploy/scripts/ensure-env.sh
"${compose[@]}" up -d --wait db
# shellcheck disable=SC2016  # intentional: expands inside the container's `sh`, not here.
"${compose[@]}" exec -T db \
  sh -c 'PGPASSWORD="$FP_OWNER_PASSWORD" exec pg_restore -h 127.0.0.1 -U fp_owner -d autobot --clean --if-exists --no-owner --no-acl' \
  <"$stage/var/backups/autobot.dump"
# pg_restore --no-acl drops the GRANT/REVOKE state; reapply roles and permissions.
"${compose[@]}" exec -T db \
  bash /docker-entrypoint-initdb.d/init-roles.sh
"${compose[@]}" run --rm web-panel \
  python manage.py apply_grants
# The key must open the restored secrets (a wrong key restores "fine" and fails later,
# when the first channel token is read): fail here, with a clear message, instead.
if ! "${compose[@]}" run --rm -T web-panel python manage.py shell -c "
from autobot.tenancy.crypto import decrypt
from autobot.tenancy.models import TenantSecret
for secret in TenantSecret.objects.using('owner'):
    decrypt(bytes(secret.ciphertext))
" >/dev/null; then
  echo 'The given SECRETS_ENCRYPTION_KEY does not decrypt the restored tenant_secret rows: wrong key. Re-run with the right one (var/.restore-incomplete stays so the retry is allowed)' >&2
  exit 1
fi
if [[ ${AUTOBOT_RESTORE_DB_ONLY:-false} != true ]]; then
  # web, web-panel, panel and victorialogs are safe and needed to verify the restore; the
  # workers are not started by default, because they would start sending with the
  # real tokens before anyone has verified the data or switched the DNS. Pass
  # AUTOBOT_RESTORE_START_WORKERS=true only when that's not a concern (e.g.
  # restore-test.sh): a *second* run of this script, after var/.deployed-sha is
  # already written, is refused above ("Existing deployment"). To start the
  # workers later, once verified, use `deploy/scripts/compose.sh up -d
  # worker-inbound worker-outbound` instead of re-running this script.
  "${compose[@]}" up -d web web-panel panel victorialogs caddy
  if [[ ${AUTOBOT_RESTORE_START_WORKERS:-false} == true ]]; then
    "${compose[@]}" up -d worker-inbound worker-outbound
  fi
fi
if [[ ${AUTOBOT_RESTORE_DB_ONLY:-false} != true ]]; then
  # Only a real restore (not a DB_ONLY rehearsal, used by restore-test.sh and server-migrate.sh's
  # destination rehearsal) marks this target as deployed; otherwise a later, real
  # restore to the same target would hit "Existing deployment" above because of
  # the rehearsal alone.
  printf '%s\n' "$SHA" >var/.deployed-sha
fi
rm -f var/.restore-incomplete
echo 'Restore completed; verify /health and per-tenant counts before DNS switch'
