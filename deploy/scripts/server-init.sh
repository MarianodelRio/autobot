#!/usr/bin/env bash
# Install Autobot on a fresh VPS from the operator's own machine (A15,
# `make server-init`). Reads var/server.env (deploy/env/server.env.example).
# Idempotent: every step checks first whether it is already done. Steps that touch
# `gh`, restic init, or a real deploy ask for confirmation before doing anything
# (CLAUDE.md: infrastructure/secrets changes need explicit human approval); none
# of this runs unattended. `--check` only does step 1 (local validation) and
# touches nothing remote.
#
# Usage: deploy/scripts/server-init.sh [--check] [--only=STEP]
#   STEP one of: validate, base, harden-ssh, secrets, restic, gh-env, deploy, panel
set -euo pipefail
cd "$(dirname "$0")/../.."

server_env=${AUTOBOT_SERVER_ENV:-var/server.env}
if [[ ! -f $server_env ]]; then
  echo "$server_env is missing; copy deploy/env/server.env.example and fill it in" >&2
  exit 1
fi
set -a
# shellcheck source=/dev/null
source "$server_env"
set +a

only=${2:-}
only=${only#--only=}
check_only=false
[[ ${1:-} == --check ]] && check_only=true

confirm() {
  local prompt=$1
  read -r -p "$prompt [y/N] " reply </dev/tty
  [[ $reply == y || $reply == Y ]]
}

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

step_validate() {
  local missing=()
  for name in HOST PUBLIC_HOST REPO_URL AUTOBOT_IMAGE AUTOBOT_PANEL_IMAGE OPERATOR_PUBKEY GOOGLE_SA_FILE; do
    [[ -n ${!name:-} ]] || missing+=("$name")
  done
  if ((${#missing[@]})); then
    echo "Missing in $server_env: ${missing[*]}" >&2
    return 1
  fi
  [[ -s $OPERATOR_PUBKEY ]] || { echo "OPERATOR_PUBKEY ($OPERATOR_PUBKEY) is missing or empty" >&2; return 1; }
  ssh-keygen -l -f "$OPERATOR_PUBKEY" >/dev/null || { echo "$OPERATOR_PUBKEY is not a valid public key" >&2; return 1; }
  [[ -s $GOOGLE_SA_FILE ]] || { echo "GOOGLE_SA_FILE ($GOOGLE_SA_FILE) is missing or empty" >&2; return 1; }
  if [[ $REPO_URL != https://* ]]; then
    echo "REPO_URL must be an https:// URL (the repo is public; no deploy key is used)" >&2
    return 1
  fi
  if command -v dig >/dev/null 2>&1; then
    resolved=$(dig +short "$PUBLIC_HOST" | tail -n 1)
    if [[ -z $resolved ]]; then
      echo "PUBLIC_HOST ($PUBLIC_HOST) does not resolve yet; fix DNS before continuing" >&2
      return 1
    fi
    if [[ -n ${HOST_IP:-} && $resolved != "$HOST_IP" ]]; then
      echo "PUBLIC_HOST resolves to $resolved, not HOST_IP ($HOST_IP)" >&2
      return 1
    fi
  else
    echo 'dig not found; skipping the DNS check (verify PUBLIC_HOST by hand)' >&2
  fi
  if command -v gh >/dev/null 2>&1; then
    gh auth status >/dev/null 2>&1 || echo 'gh is not authenticated; step gh-env will need it' >&2
  else
    echo 'gh not found; step gh-env will need it' >&2
  fi
  echo 'Local validation OK'
}

ci_key_path=var/.server-init-ci-ed25519
step_base() {
  : "${SSH_USER:=root}"
  if [[ ! -f $ci_key_path ]]; then
    ssh-keygen -t ed25519 -N '' -C autobot-ci -f "$ci_key_path" >/dev/null
  fi
  scp "${ssh_opts[@]}" deploy/scripts/bootstrap-server.sh "$SSH_USER@$HOST:/tmp/bootstrap-server.sh"
  scp "${ssh_opts[@]}" "$OPERATOR_PUBKEY" "$SSH_USER@$HOST:/tmp/operator.pub"
  scp "${ssh_opts[@]}" "$ci_key_path.pub" "$SSH_USER@$HOST:/tmp/ci.pub"
  # shellcheck disable=SC2029  # intentional: REPO_URL expands locally, into the
  # literal remote command (it would otherwise be an unset variable there).
  ssh "${ssh_opts[@]}" "$SSH_USER@$HOST" \
    "REPO_URL='$REPO_URL' bash /tmp/bootstrap-server.sh --base /tmp/operator.pub /tmp/ci.pub"
  echo 'Base bootstrap done. Open NEW sessions as deploy@ and admin@ to verify before'
  echo '--only=harden-ssh (the provider console stays your way out if either fails).'
}

step_harden_ssh() {
  if ! ssh "${ssh_opts[@]}" "deploy@$HOST" true; then
    echo 'Cannot reach deploy@HOST with the operator key; fix that before hardening SSH' >&2
    return 1
  fi
  if ! ssh "${ssh_opts[@]}" "admin@$HOST" true; then
    echo 'Cannot reach admin@HOST with the operator key; fix that before hardening SSH' >&2
    return 1
  fi
  confirm "Close root/password SSH on $HOST now?" || { echo 'Skipped' >&2; return 1; }
  ssh "${ssh_opts[@]}" "admin@$HOST" 'sudo bash /tmp/bootstrap-server.sh --harden-ssh'
}

step_secrets() {
  # Merge, never overwrite: anything ensure-env.sh already generated on the server
  # (passwords, keys) must survive. Fetch the remote .env, add/replace only what
  # this step is responsible for, and push it back.
  local tmp
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' RETURN
  ssh "${ssh_opts[@]}" "deploy@$HOST" 'cat /srv/autobot/.env 2>/dev/null || true' >"$tmp"
  for pair in "PUBLIC_HOST=$PUBLIC_HOST" "AUTOBOT_IMAGE=$AUTOBOT_IMAGE" \
    "AUTOBOT_PANEL_IMAGE=$AUTOBOT_PANEL_IMAGE" "DJANGO_ALLOWED_HOSTS=$PUBLIC_HOST,localhost,127.0.0.1" \
    "DEMO_TELEGRAM_TOKEN=${DEMO_TELEGRAM_TOKEN:-}" "NOTIFY_BOT_TOKEN=${NOTIFY_BOT_TOKEN:-}" \
    "OPS_TELEGRAM_CHAT_ID=${OPS_TELEGRAM_CHAT_ID:-}" "OWNER_SUPPORT_EMAIL=${OWNER_SUPPORT_EMAIL:-}" \
    "SENTRY_DSN=${SENTRY_DSN:-}" "HEALTHCHECKS_PING_URL=${HEALTHCHECKS_PING_URL:-}"; do
    name=${pair%%=*}
    grep -v "^$name=" "$tmp" >"$tmp.next" || true
    mv "$tmp.next" "$tmp"
    [[ -n ${pair#*=} ]] && printf '%s\n' "$pair" >>"$tmp"
  done
  ssh "${ssh_opts[@]}" "deploy@$HOST" 'install -m 600 /dev/stdin /srv/autobot/.env' <"$tmp"
  ssh "${ssh_opts[@]}" "deploy@$HOST" 'install -m 600 /dev/stdin /srv/autobot/var/google_sa.json' <"$GOOGLE_SA_FILE"
  if [[ -n ${RESTIC_REPOSITORY:-} ]]; then
    {
      printf 'RESTIC_REPOSITORY=%s\n' "$RESTIC_REPOSITORY"
      printf 'RESTIC_PASSWORD_FILE=/srv/autobot/var/restic-password\n'
      printf 'AWS_ACCESS_KEY_ID=%s\n' "${AWS_ACCESS_KEY_ID:-}"
      printf 'AWS_SECRET_ACCESS_KEY=%s\n' "${AWS_SECRET_ACCESS_KEY:-}"
      printf 'HEALTHCHECKS_BACKUP_PING_URL=%s\n' "${HEALTHCHECKS_BACKUP_PING_URL:-}"
    } | ssh "${ssh_opts[@]}" "deploy@$HOST" 'install -m 600 /dev/stdin /srv/autobot/var/backup.env'
  fi
  if [[ -s ${RESTIC_PASSWORD_FILE:-/dev/null} ]]; then
    ssh "${ssh_opts[@]}" "deploy@$HOST" 'install -m 600 /dev/stdin /srv/autobot/var/restic-password' \
      <"$RESTIC_PASSWORD_FILE"
  fi
  ssh "${ssh_opts[@]}" "deploy@$HOST" '/srv/autobot/deploy/scripts/ensure-env.sh'
  echo 'Secrets uploaded (.env merged, never overwritten)'
}

step_restic() {
  if ssh "${ssh_opts[@]}" "deploy@$HOST" \
    'AUTOBOT_BACKUP_CONFIG=/srv/autobot/var/backup.env bash -c "set -a; . \"$AUTOBOT_BACKUP_CONFIG\"; restic cat config"' \
    >/dev/null 2>&1; then
    echo 'Restic repository already initialized'
  else
    confirm "Run 'restic init' on $RESTIC_REPOSITORY now (A3: never automatic)?" || return 1
    ssh "${ssh_opts[@]}" "deploy@$HOST" \
      'AUTOBOT_BACKUP_CONFIG=/srv/autobot/var/backup.env bash -c "set -a; . \"$AUTOBOT_BACKUP_CONFIG\"; restic init"'
  fi
  # First run also records var/.restic-repo-id (A3), so later timer runs can tell
  # a misconfigured destination apart from the real repository.
  ssh "${ssh_opts[@]}" "deploy@$HOST" '/srv/autobot/deploy/scripts/backup.sh'
  ssh "${ssh_opts[@]}" "admin@$HOST" 'sudo systemctl start autobot-backup.timer'
}

step_gh_env() {
  command -v gh >/dev/null 2>&1 || { echo 'gh not found' >&2; return 1; }
  confirm 'Create/update the "production" GitHub environment and its deploy secrets now?' || return 1
  gh api -X PUT "repos/{owner}/{repo}/environments/production" >/dev/null
  gh secret set DEPLOY_HOST --env production --body "$HOST"
  gh secret set DEPLOY_SSH_KEY --env production <"${OPERATOR_PUBKEY%.pub}"
  ssh-keyscan -H "$HOST" | gh secret set DEPLOY_KNOWN_HOSTS --env production
  echo 'production environment configured'
}

step_deploy() {
  local sha
  sha=$(git rev-parse HEAD)
  confirm "Deploy $sha to $HOST now (the first deploy; run directly over SSH, not through the GitHub Actions workflow)?" \
    || return 1
  # Run directly instead of through the GitHub Actions workflow: this is a public
  # repo, and the first deploy is the one most likely to need a look at full,
  # unredacted output, which Actions logs on a public repo are not the place for.
  # shellcheck disable=SC2029  # intentional: sha expands locally, into the literal remote command.
  ssh "${ssh_opts[@]}" "deploy@$HOST" "cd /srv/autobot && git fetch --quiet origin main && git checkout --quiet --detach $sha && deploy/scripts/deploy.sh $sha"
}

step_panel() {
  # shellcheck disable=SC2029  # intentional: PANEL_USER expands locally.
  ssh "${ssh_opts[@]}" "deploy@$HOST" \
    "/srv/autobot/deploy/scripts/manage.sh panel_user exists ${PANEL_USER:-panel} || /srv/autobot/deploy/scripts/manage.sh panel_user create ${PANEL_USER:-panel}"
  echo 'Register channel webhooks and run the first backup by hand once tokens are set.'
}

run() {
  local name=$1 fn=$2
  if [[ -n $only && $only != "$name" ]]; then
    return 0
  fi
  echo "== $name =="
  "$fn"
}

run validate step_validate
if [[ $check_only == true ]]; then
  exit 0
fi
run base step_base
run harden-ssh step_harden_ssh
run secrets step_secrets
run restic step_restic
run gh-env step_gh_env
run deploy step_deploy
run panel step_panel
echo 'server-init.sh finished'
