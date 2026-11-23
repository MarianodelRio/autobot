#!/usr/bin/env bash
# Prepares .env for a deploy, called at the start of deploy.sh:
#   - generates the internal secrets that are missing (passwords, keys, DB_*_URL);
#   - never invents an external credential (Meta, Telegram, Sentry...); aborts and
#     lists whatever external variable is missing instead;
#   - never prints a value, only variable names;
#   - generates SECRETS_ENCRYPTION_KEY only with --first-install (ADR-022): on an existing
#     install a missing key must be restored from the password manager, never replaced,
#     or every tenant_secret becomes unreadable.
set -euo pipefail
first_install=false
for arg in "$@"; do
  case $arg in
    --first-install) first_install=true ;;
    *) echo "Unknown argument: $arg (only --first-install is accepted)" >&2; exit 2 ;;
  esac
done
cd "$(dirname "$0")/../.."

ENV_FILE=.env
if [[ ! -f $ENV_FILE ]]; then
  : >"$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

random_secret() {
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
}

fernet_key() {
  python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
}

generated_names=()
generated_lines=()

generate_if_missing() {
  local name=$1 generator=$2 value
  [[ -n ${!name:-} ]] && return 0
  value=$(eval "$generator")
  export "$name=$value"
  generated_names+=("$name")
  generated_lines+=("$name=$value")
}

for name in FP_OWNER_PASSWORD FP_APP_PASSWORD FP_READONLY_PASSWORD POSTGRES_PASSWORD \
  DJANGO_SECRET_KEY DEMO_TELEGRAM_WEBHOOK_SECRET NOTIFY_BOT_WEBHOOK_SECRET; do
  generate_if_missing "$name" random_secret
done
if [[ -z ${SECRETS_ENCRYPTION_KEY:-} ]]; then
  if [[ $first_install != true ]]; then
    cat >&2 <<'MSG'
SECRETS_ENCRYPTION_KEY is missing from .env and this is not a first install, so it will NOT be generated:
a new key would make every channel secret in the database unreadable (ADR-022).
Put back the key kept in the password manager (see docs/procedimientos/rotar-secretos.md),
or restore with restore.sh, which takes it explicitly. Only on a brand-new server with no
data, run: deploy/scripts/ensure-env.sh --first-install
MSG
    exit 1
  fi
  generate_if_missing SECRETS_ENCRYPTION_KEY fernet_key
  echo 'A NEW SECRETS_ENCRYPTION_KEY was generated: save it NOW in the password manager (it is not in backups)' >&2
fi

# The DB_*_URL are derived from the FP_*_PASSWORD, never independent of them: they
# are generated when missing and re-derived whenever they stop matching, so rotating
# a password in .env (and re-running deploy.sh, whose init-roles.sh applies it to the
# role) can never leave a URL with the old one. See rotar-secretos.md.
# FP_*_PASSWORD come from `secrets.token_urlsafe`, which needs no URL-encoding; a
# hand-picked password with reserved characters has to be percent-encoded here.
url_password() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}
sync_db_url() {
  local name=$1 role=$2 password_var=$3 value
  value="postgres://${role}:$(url_password "${!password_var}")@db:5432/autobot"
  [[ ${!name:-} == "$value" ]] && return 0
  if [[ -n ${!name:-} && ${!name} != *localhost* ]]; then
    echo "$name did not match $password_var; re-derived it" >&2
  fi
  export "$name=$value"
  generated_names+=("$name")
  generated_lines+=("$name=$value")
}

# Not secrets: enforced, not just generated when missing, so a server .env never
# drifts to a stale compose file list or project name.
ensure_fixed() {
  local name=$1 value=$2
  [[ ${!name:-} == "$value" ]] && return 0
  export "$name=$value"
  generated_names+=("$name")
  generated_lines+=("$name=$value")
}
ensure_fixed COMPOSE_FILE 'deploy/compose/compose.yaml:deploy/compose/compose.prod.yaml'
ensure_fixed COMPOSE_PROJECT_NAME autobot

# Catch a .env.example value copied as-is into a server .env: generation above only
# fills in what's missing, so an example value that's already "set" would pass through.
reject_example_value() {
  local name=$1 example=$2
  [[ ${!name:-} == "$example" ]] || return 0
  echo "$name is still the .env.example value; set a real one" >&2
  exit 1
}
reject_example_value DJANGO_SECRET_KEY change-me
reject_example_value SECRETS_ENCRYPTION_KEY 'UHx17yr1uv1SdskJ5dGpF1MYUPfD2ierqd5mY_2AQ_w='

reject_localhost_url() {
  local name=$1
  [[ ${!name:-} == *localhost* ]] || return 0
  echo "$name must not point to localhost in production" >&2
  exit 1
}
reject_localhost_url DB_APP_URL
reject_localhost_url DB_OWNER_URL
reject_localhost_url DB_READONLY_URL
sync_db_url DB_APP_URL fp_app FP_APP_PASSWORD
sync_db_url DB_OWNER_URL fp_owner FP_OWNER_PASSWORD
sync_db_url DB_READONLY_URL fp_readonly FP_READONLY_PASSWORD

# Appends whatever generate_if_missing/ensure_fixed collected so far and clears the
# arrays; called twice, so secrets are saved even if a later check aborts the script.
flush_generated() {
  if ((${#generated_lines[@]})); then
    {
      printf '\n# ensure-env.sh generated these on %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf '%s\n' "${generated_lines[@]}"
    } >>"$ENV_FILE"
    printf 'Generated: %s\n' "${generated_names[*]}"
  fi
  generated_names=()
  generated_lines=()
}
flush_generated

missing=()
for name in PUBLIC_HOST DJANGO_ALLOWED_HOSTS AUTOBOT_IMAGE AUTOBOT_PANEL_IMAGE; do
  [[ -n ${!name:-} ]] || missing+=("$name")
done
if ((${#missing[@]})); then
  printf 'Missing required variables in .env: %s\n' "${missing[*]}" >&2
  exit 1
fi

hosts=",${DJANGO_ALLOWED_HOSTS},"
if [[ $hosts != *",127.0.0.1,"* || $hosts != *",localhost,"* ]]; then
  echo 'DJANGO_ALLOWED_HOSTS must include both 127.0.0.1 and localhost (the panel tunnel reaches web with that host)' >&2
  exit 1
fi

# the deploy user's uid can differ between hosts, and a restored .env carries
# the uid of whichever host it was backed up from; always derive it here instead of
# trusting a value set by hand (ensure-env.sh runs on restore.sh's target too).
# Never root: run by mistake as root, DEPLOY_UID=0 would run every container as root.
if [[ $(id -u) == 0 ]]; then
  echo 'Run this as the deploy user, never as root (DEPLOY_UID would become 0)' >&2
  exit 1
fi
ensure_fixed DEPLOY_UID "$(id -u)"
public_url() {
  echo "https://$PUBLIC_HOST"
}
# PUBLIC_URL is only the webhook base built from PUBLIC_HOST; derive it so
# nobody has to keep the two in sync by hand.
generate_if_missing PUBLIC_URL public_url
flush_generated

# a missing google_sa.json would otherwise make Docker create a directory in its
# place when it binds the volume (`../../var/google_sa.json:/run/secrets/...`),
# which then fails much later with a confusing error.
if [[ ! -f var/google_sa.json ]]; then
  echo 'var/google_sa.json is missing or is not a regular file' >&2
  exit 1
fi
