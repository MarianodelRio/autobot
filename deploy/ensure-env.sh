#!/usr/bin/env bash
# Prepares .env for a deploy, called at the start of deploy.sh:
#   - generates the internal secrets that are missing (passwords, keys, DB_*_URL);
#   - never invents an external credential (Meta, Telegram, Sentry...); aborts and
#     lists whatever external variable is missing instead;
#   - never prints a value, only variable names.
set -euo pipefail
cd "$(dirname "$0")/.."

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
generate_if_missing SECRETS_ENCRYPTION_KEY fernet_key

generate_db_url() {
  local name=$1 role=$2 password_var=$3
  [[ -n ${!name:-} ]] && return 0
  local value="postgres://${role}:${!password_var}@db:5432/autobot"
  export "$name=$value"
  generated_names+=("$name")
  generated_lines+=("$name=$value")
}
generate_db_url DB_APP_URL fp_app FP_APP_PASSWORD
generate_db_url DB_OWNER_URL fp_owner FP_OWNER_PASSWORD
generate_db_url DB_READONLY_URL fp_readonly FP_READONLY_PASSWORD

if ((${#generated_lines[@]})); then
  {
    printf '\n# ensure-env.sh generated these on %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\n' "${generated_lines[@]}"
  } >>"$ENV_FILE"
  printf 'Generated: %s\n' "${generated_names[*]}"
fi

missing=()
for name in PUBLIC_HOST DJANGO_ALLOWED_HOSTS DEPLOY_UID; do
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
