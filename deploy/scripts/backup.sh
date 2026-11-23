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
# RESTIC_PASSWORD_FILE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and ping URL. The S3
# key in it must be an UPLOAD-ONLY credential (no delete permission, ADR-021): a
# compromised server can add snapshots but cannot erase the history. Expiring old
# snapshots (`forget --prune`) is deploy/scripts/backup-prune.sh, run from the
# operator's machine with a different credential that never lives here; this script
# only READS when that last happened (prune_state, below) so ops can alert if nobody did.
# shellcheck source=/dev/null
source "$backup_config"
: "${RESTIC_REPOSITORY:?}"
: "${RESTIC_PASSWORD_FILE:?}"
: "${HEALTHCHECKS_BACKUP_PING_URL:?}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export HEALTHCHECKS_BACKUP_PING_URL
# `restic backup` always takes a repository lock (it ignores --no-lock) and deletes it when
# it ends, so the upload-only credential may delete objects under `locks/` and nowhere else
# (docs/procedimientos/backups.md). That also keeps restic's locking real: a prune run from
# the operator's machine and this backup exclude each other.
restic_bin=${RESTIC_BIN:-restic}

mkdir -p var/backups var/state/ops
dump_tmp=$(mktemp var/backups/.autobot.dump.XXXXXXXX)
env_stage=var/backups/autobot.env
ledger_file=var/backups/privacy-ledger.jsonl
ledger_tmp=var/backups/.privacy-ledger.tmp
ledger_ok=true
dump_bytes=0
# The size of the last good dump stays in backup.json when this run fails before
# producing one: it is the reference for the free-space check of the next run.
last_dump_bytes=$(python3 -c 'import json,sys
try:
    print(int(json.load(open(sys.argv[1]))["dump_bytes"]))
except Exception:
    print(0)' var/state/ops/backup.json 2>/dev/null) || last_dump_bytes=0
[[ $last_dump_bytes =~ ^[0-9]+$ ]] || last_dump_bytes=0
deployed_sha_stage=var/backups/deployed-sha

# Runs on every exit, success or failure: records the outcome for the panel and
# never leaves the plaintext dump on disk once restic has it.
write_status() {
  local code=$? ok=false status_tmp
  [[ $code -eq 0 ]] && ok=true
  rm -f "$dump_tmp" var/backups/autobot.dump "$env_stage" "$ledger_file" "$ledger_tmp" "$deployed_sha_stage"
  ((dump_bytes > 0)) || dump_bytes=$last_dump_bytes
  status_tmp=$(mktemp var/state/ops/.backup.json.XXXXXXXX)
  printf '{"finished_at":"%s","ok":%s,"dump_bytes":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$dump_bytes" >"$status_tmp"
  mv "$status_tmp" var/state/ops/backup.json
}
trap write_status EXIT

# `restic init` is never automatic here. A repository created by mistake (a
# typo in RESTIC_REPOSITORY, or credentials that happen to also reach some other,
# empty bucket) would otherwise look like a successful backup forever, silently
# hiding that the real repository was never written to. Init it once by hand, then
# record its id below so every later run can tell "misconfigured, empty bucket"
# apart from "the one true repository".
config=$("$restic_bin" cat config) || {
  echo 'Restic repository is not initialized (this is never done automatically); run restic init once by hand' >&2
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

# Free space: the dump is written to disk first (and removed on exit). Require twice
# the size of the last successful dump (or AUTOBOT_BACKUP_MIN_FREE_BYTES, 512 MiB by
# default, if that is bigger or unknown), so a full disk fails here, loudly, instead
# of leaving a truncated dump for restic to upload.
min_free=${AUTOBOT_BACKUP_MIN_FREE_BYTES:-536870912}
required=$((last_dump_bytes * 2))
((required > min_free)) || required=$min_free
free_bytes=$(df --output=avail -B1 var/backups | tail -n 1 | tr -d ' ')
if [[ ! $free_bytes =~ ^[0-9]+$ ]] || ((free_bytes < required)); then
  echo "Not enough free disk space for the dump (${free_bytes:-?} bytes free, $required needed)" >&2
  exit 1
fi

# A deploy changes the schema and var/.deployed-sha in two separate steps; a snapshot
# taken in between would pair a new schema with the old SHA, and restore.sh would then
# bring up old code on a migrated database. Hold deploy.sh's lock in shared mode (like
# prune.sh: it only ever blocks against a deploy's exclusive one, never another backup)
# from before the SHA is read until the dump is verified, and keep that SHA as its own
# staged file, which restore.sh prefers: the upload below runs without the lock, and
# var/.deployed-sha may move on while it does. If a deploy outlasts the wait, the run fails
# visibly (ok=false in backup.json, no ping) and the next hourly one takes its turn.
exec 8>var/.deploy.lock
if ! flock -s -w "${AUTOBOT_BACKUP_DEPLOY_LOCK_WAIT:-300}" 8; then
  echo 'A deployment held its lock for too long; backup skipped (it fails visibly, the next run retries)' >&2
  exit 1
fi
cp var/.deployed-sha "$deployed_sha_stage"
test -s "$deployed_sha_stage"

"${compose[@]}" exec -T db \
  pg_dump -U postgres -d autobot -Fc >"$dump_tmp"
test -s "$dump_tmp"
# A truncated or corrupt dump must never reach restic (and, through retention,
# replace a good one): pg_restore --list reads the whole table of contents, which
# a cut-off custom-format dump does not have. Run with the database's own
# pg_restore, the same version that would restore it.
if ! "${compose[@]}" exec -T db pg_restore --list <"$dump_tmp" >/dev/null; then
  echo 'The dump failed pg_restore --list; not uploading it' >&2
  exit 1
fi
mv "$dump_tmp" var/backups/autobot.dump
dump_bytes=$(stat -c '%s' var/backups/autobot.dump)
flock -u 8  # the dump and the SHA that matches it are staged; a deploy may proceed now

# The Fernet key (SECRETS_ENCRYPTION_KEY, which decrypts every tenant_secret row of the
# dump) must not travel in the same snapshot as the data it protects (ADR-021): the
# snapshot gets the .env without that one line, and the operator keeps the key
# separately (docs/procedimientos/rotar-secretos.md). restore.sh asks for it explicitly.
# var/google_sa.json stays in the snapshot on purpose: it is not a data key, it can only
# reach calendars shared with that service account, and it can be revoked and re-issued
# from Google at any time.
grep -vE '^[[:space:]]*(export[[:space:]]+)?SECRETS_ENCRYPTION_KEY=' .env >"$env_stage" || true
if grep -qE 'SECRETS_ENCRYPTION_KEY' "$env_stage"; then
  echo 'The staged .env still mentions SECRETS_ENCRYPTION_KEY; not uploading it' >&2
  exit 1
fi
test -s "$env_stage"
backup_paths=("$env_stage" var/backups/autobot.dump "$deployed_sha_stage" var/.deployed-sha var/google_sa.json deploy/caddy/Caddyfile)
# Caddy's own state (its ACME account and certificates: losing them means
# reissuing from scratch) and the deploy log. Optional: missing on a target that
# was bootstrapped but never deployed to yet, which must not fail the backup.
for optional_path in var/state/caddy-data var/state/caddy-config var/state/ops/deploys.jsonl; do
  [[ -e $optional_path ]] && backup_paths+=("$optional_path")
done
"$restic_bin" backup --tag autobot "${backup_paths[@]}"

# The suppression ledger (ADR-019, ADR-025) as its own tiny snapshot, tagged
# autobot-ledger: restore.sh takes the LATEST one (not the one of the snapshot it
# restores), so an erasure made after the last full snapshot is still reapplied. It
# holds ids and HMACs only, no personal data. The export runs in a one-off web-panel
# container (read-only, like manage.sh) and prints to stdout, where the container's own
# startup logs also land: only the marked lines are kept. A failure must not stop the
# database backup above, but it must not pass silently either: it is reported at the end,
# before the ping.
ledger_snapshot() {
  local raw
  raw=$("${compose[@]}" run --rm --no-deps -T web-panel python manage.py privacy_ledger_export) || return 1
  { printf '%s\n' "$raw" | grep -F '"ledger": "privacy.v1"' || true; } >"$ledger_tmp" || return 1
  mv "$ledger_tmp" "$ledger_file" || return 1
  "$restic_bin" backup --tag autobot-ledger "$ledger_file"
}
ledger_snapshot || {
  ledger_ok=false
  echo 'Could not export and upload the suppression ledger (ADR-025)' >&2
}

# When did the operator last prune? backup-prune.sh uploads a tiny snapshot tagged
# autobot-prune after each successful run; the oldest `autobot` snapshot covers a
# repository that was never pruned. The result lands in var/state/ops/backup-prune.json,
# which ops_check reads (backup_prune_overdue). Read-only and best effort: a repository
# that cannot be listed just leaves the previous file (the backup itself already passed).
prune_state() {
  local prune_json autobot_json tmp
  prune_json=$("$restic_bin" --no-lock snapshots --tag autobot-prune --json) || return 1
  autobot_json=$("$restic_bin" --no-lock snapshots --tag autobot --json) || return 1
  tmp=$(mktemp var/state/ops/.backup-prune.json.XXXXXXXX) || return 1
  if python3 -I -c 'import json, re, sys
from datetime import UTC, datetime


def times(text):
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        for snap in item.get("snapshots", [item]) if isinstance(item, dict) else []:
            when = snap.get("time") if isinstance(snap, dict) else None
            if isinstance(when, str):
                out.append(re.sub(r"(\.\d{6})\d+", r"\1", when))
    return sorted(out, key=lambda t: datetime.fromisoformat(t).timestamp())


prunes, autobots = times(sys.argv[1]), times(sys.argv[2])
print(json.dumps({
    "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "last_prune_at": prunes[-1] if prunes else None,
    "oldest_snapshot_at": autobots[0] if autobots else None,
}))' "$prune_json" "$autobot_json" >"$tmp"; then
    mv "$tmp" var/state/ops/backup-prune.json
  else
    rm -f "$tmp"
    return 1
  fi
}
prune_state || echo 'Could not read the prune marker; backup-prune.json not refreshed' >&2
# No `forget`/`--prune` here (ADR-021): expiring snapshots needs delete permission, which
# this host's credential does not have. deploy/scripts/backup-prune.sh does it from the
# operator's machine.
# Weekly integrity check of a random subset of the pack data, not just the index
# (`restic backup` only ever checks what it uploads): catches a bucket that is
# silently corrupting or losing objects while backups keep "succeeding". It runs on
# the first backup of each ISO week and fails the run *before* the ping, so
# Healthchecks notices; the week is only recorded once the check passes. The
# subset (AUTOBOT_RESTIC_CHECK_SUBSET, 5% by default) keeps it cheap on a
# provider that charges for reads.
check_marker=var/.last-restic-check
this_week=$(date -u +%G-W%V)
if [[ ! -f $check_marker || $(cat "$check_marker") != "$this_week" ]]; then
  "$restic_bin" check --read-data-subset="${AUTOBOT_RESTIC_CHECK_SUBSET:-5%}"
  printf '%s' "$this_week" >"$check_marker"
fi
if [[ $ledger_ok != true ]]; then
  echo 'Backup finished without a fresh suppression ledger; not pinging' >&2
  exit 1
fi
python3 -c 'import os, urllib.request; urllib.request.urlopen(os.environ["HEALTHCHECKS_BACKUP_PING_URL"], timeout=10).close()'
echo 'Backup completed'
