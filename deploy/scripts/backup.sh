#!/usr/bin/env bash
# Run from the host timer as deploy; backup credentials live outside this repository.
set -euo pipefail
# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
umask 077
mkdir -p var
exec 9>var/.backup.lock
flock -n 9 || { echo 'Another backup is running' >&2; exit 1; }

backup_config=${AUTOBOT_BACKUP_CONFIG:-/srv/autobot/var/backup.env}
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

mkdir -p var/backups var/state/ops
dump_tmp=$(mktemp var/backups/.autobot.dump.XXXXXXXX)
dump_bytes=0

# Runs on every exit, success or failure: records the outcome for the panel and
# never leaves the plaintext dump on disk once restic has it.
write_status() {
  local code=$? ok=false status_tmp
  [[ $code -eq 0 ]] && ok=true
  rm -f "$dump_tmp" var/backups/autobot.dump
  status_tmp=$(mktemp var/state/ops/.backup.json.XXXXXXXX)
  printf '{"finished_at":"%s","ok":%s,"dump_bytes":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$dump_bytes" >"$status_tmp"
  mv "$status_tmp" var/state/ops/backup.json
}
trap write_status EXIT

# A3: `restic init` is never automatic here. A repository created by mistake (a
# typo in RESTIC_REPOSITORY, or credentials that happen to also reach some other,
# empty bucket) would otherwise look like a successful backup forever, silently
# hiding that the real repository was never written to. Init it once by hand, then
# record its id below so every later run can tell "misconfigured, empty bucket"
# apart from "the one true repository".
config=$("$restic_bin" cat config) || {
  echo 'Restic repository is not initialized (A3: this is never done automatically); run restic init once by hand' >&2
  exit 1
}
repo_id=$(printf '%s' "$config" | sed -n 's/.*"id":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
if [[ -z $repo_id ]]; then
  echo 'Could not read the restic repository id from restic cat config' >&2
  exit 1
fi
repo_id_file=var/.restic-repo-id
if [[ -f $repo_id_file ]]; then
  expected_repo_id=$(cat "$repo_id_file")
  if [[ $repo_id != "$expected_repo_id" ]]; then
    echo "Restic repository id ($repo_id) does not match var/.restic-repo-id ($expected_repo_id); refusing to back up to what looks like a different repository" >&2
    exit 1
  fi
else
  # First backup against this repository from this host: remember its id.
  printf '%s' "$repo_id" >"$repo_id_file"
fi

"${compose[@]}" exec -T db \
  pg_dump -U postgres -d autobot -Fc >"$dump_tmp"
test -s "$dump_tmp"
mv "$dump_tmp" var/backups/autobot.dump
dump_bytes=$(stat -c '%s' var/backups/autobot.dump)

backup_paths=(var/backups/autobot.dump .env var/.deployed-sha var/google_sa.json deploy/caddy/Caddyfile)
# T2: Caddy's own state (its ACME account and certificates: losing them means
# reissuing from scratch) and the deploy log. Optional: missing on a target that
# was bootstrapped but never deployed to yet, which must not fail the backup.
for optional_path in var/state/caddy-data var/state/caddy-config var/state/ops/deploys.jsonl; do
  [[ -e $optional_path ]] && backup_paths+=("$optional_path")
done
"$restic_bin" backup --tag autobot "${backup_paths[@]}"
# Group by tag: the dump path stays constant and all snapshots use the same policy.
forget_args=(--tag autobot --group-by tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6)
# T5: hourly backups make `forget` run hourly too, but `--prune` actually rewrites
# the repository (lists every pack in it) and most providers charge for that; once
# a day is often enough to reclaim space from expired snapshots.
prune_marker=var/.last-prune
today=$(date -u +%Y-%m-%d)
if [[ ! -f $prune_marker || $(cat "$prune_marker") != "$today" ]]; then
  "$restic_bin" forget "${forget_args[@]}" --prune
  printf '%s' "$today" >"$prune_marker"
else
  "$restic_bin" forget "${forget_args[@]}"
fi
python3 -c 'import os, urllib.request; urllib.request.urlopen(os.environ["HEALTHCHECKS_BACKUP_PING_URL"], timeout=10).close()'
echo 'Backup completed'
