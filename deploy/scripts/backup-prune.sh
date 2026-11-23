#!/usr/bin/env bash
# Expire old backup snapshots (`restic forget --prune`) FROM THE OPERATOR'S MACHINE, never
# from the server (ADR-021). The server's timer only uploads: its S3 credential has no
# permission to delete, so a compromised server cannot erase the history. Deleting needs a
# second credential that lives only here, outside the server and outside git.
#
#   deploy/scripts/backup-prune.sh [--dry-run]
#
# Reads AUTOBOT_PRUNE_CONFIG (default ~/.config/autobot/backup-prune.env, mode 0600):
#   RESTIC_REPOSITORY=s3:https://...        # the same repository the server uploads to
#   RESTIC_PASSWORD_FILE=/path/to/password  # or RESTIC_PASSWORD_COMMAND=...: the repository password
#   AWS_ACCESS_KEY_ID=...                   # a DIFFERENT key, with s3:DeleteObject on that bucket
#   AWS_SECRET_ACCESS_KEY=...
# See docs/procedimientos/backups.md for the bucket policy and when to run it.
set -euo pipefail

# The server holds only the upload-only credential; running this there would need the
# delete one to be copied to it, which is exactly what must not happen.
if [[ -f ${AUTOBOT_BOOTSTRAP_MARKER:-/var/lib/autobot/bootstrap-complete} && ${AUTOBOT_PRUNE_ALLOW_ON_SERVER:-false} != true ]]; then
  echo 'This looks like the Autobot server (bootstrap marker present). Run backup-prune.sh from the operator machine, with the delete credential that never lives on the server.' >&2
  exit 1
fi

dry_run=()
case ${1:-} in
  '') ;;
  --dry-run) dry_run=(--dry-run) ;;
  *)
    echo 'Usage: deploy/scripts/backup-prune.sh [--dry-run]' >&2
    exit 2
    ;;
esac

prune_config=${AUTOBOT_PRUNE_CONFIG:-$HOME/.config/autobot/backup-prune.env}
if [[ ! -f $prune_config ]]; then
  echo "Prune configuration is missing: $prune_config (see deploy/env/backup.env.example)" >&2
  exit 1
fi
if [[ $(stat -c '%a' "$prune_config") != 600 ]]; then
  echo "$prune_config must have mode 0600: it holds a credential that can delete backups" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$prune_config"
: "${RESTIC_REPOSITORY:?}"
: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"
if [[ -z ${RESTIC_PASSWORD_FILE:-} && -z ${RESTIC_PASSWORD_COMMAND:-} ]]; then
  echo 'Set RESTIC_PASSWORD_FILE or RESTIC_PASSWORD_COMMAND in the prune configuration' >&2
  exit 1
fi
export RESTIC_REPOSITORY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
[[ -z ${RESTIC_PASSWORD_FILE:-} ]] || export RESTIC_PASSWORD_FILE
[[ -z ${RESTIC_PASSWORD_COMMAND:-} ]] || export RESTIC_PASSWORD_COMMAND
restic_bin=${RESTIC_BIN:-restic}

# restic's exclusive lock keeps a prune and the server's hourly backup (autobot-backup.timer,
# at :00) apart, but the loser fails: a backup that finds the repository locked fails that
# hour (and alerts), a prune that finds the backup's lock stops. Run it away from the top
# of the hour. If it reports a stale lock (a backup that died), check var/state/ops/backup.json
# on the server and clear it from here with `restic unlock`.
if [[ ${#dry_run[@]} -eq 0 && ${AUTOBOT_PRUNE_ANYTIME:-false} != true ]]; then
  minute=$((10#$(date +%M)))
  if ((minute < 15 || minute > 50)); then
    echo "Minute $minute is inside the server's backup window (hourly backups start at :00 and may run until about :15): run this between :15 and :50, or set AUTOBOT_PRUNE_ANYTIME=true if the timer is stopped" >&2
    exit 1
  fi
fi

# Same policy that backup.sh applied before ADR-021. Grouped by tag: the dump path is
# constant and every snapshot follows the same policy.
"$restic_bin" forget --tag autobot --group-by tags \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune "${dry_run[@]}"
# The suppression-ledger snapshots (hourly, tag autobot-ledger, ADR-025) are tiny and
# restore.sh only needs the latest, but a few weeks of history cost nothing.
"$restic_bin" forget --tag autobot-ledger --group-by tags \
  --keep-daily 7 --keep-weekly 4 --prune "${dry_run[@]}"
# Proof of this run for the server (ADR-025): a tiny snapshot tagged autobot-prune. The
# server's backup.sh reads its time (never writes it with a delete permission) and
# ops_check raises backup_prune_overdue if it is older than 10 days. Only after the
# forgets above succeeded (set -e), never on a dry run; the previous markers are
# expired right after, keeping the last three.
if [[ ${#dry_run[@]} -eq 0 ]]; then
  printf 'pruned\n' | "$restic_bin" backup --stdin --stdin-filename prune-marker --tag autobot-prune
  "$restic_bin" forget --tag autobot-prune --group-by tags --keep-last 3 --prune
fi
echo 'Prune completed'
