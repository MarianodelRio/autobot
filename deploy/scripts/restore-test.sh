#!/usr/bin/env bash
# Disposable local backup/restore exercise; needs Docker and restic, no real services.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck source=./lib.sh
AUTOBOT_LIB_FUNCTIONS_ONLY=1 source deploy/scripts/lib.sh
: "${RESTIC_BIN:=restic}"
command -v "$RESTIC_BIN" >/dev/null
test_root=$(mktemp -d)
source_dir=$test_root/source
target_dir=$test_root/target
for dir in "$source_dir" "$target_dir"; do
  mkdir -p "$dir/deploy/compose" "$dir/deploy/postgres" "$dir/deploy/caddy" "$dir/deploy/scripts" \
    "$dir/var"
  # Like install-vm.sh on the real VPS: pre-create the bind-mount sources so Docker
  # never auto-creates them as root when a container starts before backup.sh does
  # (`var/state/ops` is mounted read-only into web-panel/worker).
  ensure_state_dirs "$dir"
done
sha=$(python3 -c 'import secrets; print(secrets.token_hex(20))')
source_project="fp-restore-src-${sha:0:8}"
target_project="fp-restore-dst-${sha:0:8}"
ping_pid=''
cleanup() {
  if [[ -n $ping_pid ]]; then
    kill "$ping_pid" >/dev/null 2>&1 || true
  fi
  compose_in "$source_dir" "$source_project" down -v >/dev/null 2>&1 || true
  compose_in "$target_dir" "$target_project" down -v >/dev/null 2>&1 || true
  docker image rm "ghcr.io/example-owner/autobot:$sha" >/dev/null 2>&1 || true
  rm -rf "$test_root"
}
trap cleanup EXIT

for dir in "$source_dir" "$target_dir"; do
  cp deploy/compose/compose.yaml deploy/compose/compose.prod.yaml "$dir/deploy/compose/"
  cp deploy/caddy/Caddyfile "$dir/deploy/caddy/"
  cp deploy/postgres/init-roles.sh "$dir/deploy/postgres/"
  cp deploy/scripts/backup.sh deploy/scripts/restore.sh deploy/scripts/lib.sh \
    deploy/scripts/ensure-env.sh "$dir/deploy/scripts/"
done
# The key is kept OUTSIDE the snapshot (ADR-021): backup.sh strips it from the staged .env
# and restore.sh gets it explicitly, here through a file like an operator would.
secrets_key=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
printf '%s\n' "$secrets_key" >"$test_root/secrets-key"
chmod 600 "$test_root/secrets-key"
cat >"$source_dir/.env" <<EOF
ENVIRONMENT=prod
PUBLIC_HOST=localhost
SHA=$sha
AUTOBOT_IMAGE=ghcr.io/example-owner/autobot
AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel
DEPLOY_UID=$(id -u)
DJANGO_SECRET_KEY=local-restore-test-only
SECRETS_ENCRYPTION_KEY=$secrets_key
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DB_APP_URL=postgres://fp_app:local@db:5432/autobot
DB_OWNER_URL=postgres://fp_owner:local@db:5432/autobot
DB_READONLY_URL=postgres://fp_readonly:local@db:5432/autobot
POSTGRES_PASSWORD=local
FP_OWNER_PASSWORD=local
FP_APP_PASSWORD=local
FP_READONLY_PASSWORD=local
EOF
printf '{}\n' >"$source_dir/var/google_sa.json"
printf '%s\n' "$sha" >"$source_dir/var/.deployed-sha"
printf '%s\n' local-restore-password >"$test_root/restic-password"
chmod 600 "$source_dir/.env" \
  "$source_dir/var/google_sa.json" "$test_root/restic-password"
cat >"$test_root/ping.py" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
Path(sys.argv[1]).write_text(str(server.server_port))
server.serve_forever()
PY
python3 "$test_root/ping.py" "$test_root/ping.port" &
ping_pid=$!
for ((i=0; i<50; i++)); do
  [[ -s $test_root/ping.port ]] && break
  sleep 0.1
done
test -s "$test_root/ping.port"
ping_port=$(cat "$test_root/ping.port")
cat >"$test_root/backup.env" <<EOF
RESTIC_REPOSITORY=$test_root/repository
RESTIC_PASSWORD_FILE=$test_root/restic-password
HEALTHCHECKS_BACKUP_PING_URL=http://127.0.0.1:$ping_port/local-only
EOF
chmod 600 "$test_root/backup.env"
export AUTOBOT_BACKUP_CONFIG="$test_root/backup.env"
# backup.sh never runs `restic init` itself; do it once here, like the
# operator does by hand on a real server, and record the repository's id the
# same way the first real backup would (so backup.sh's id check doesn't trip).
RESTIC_REPOSITORY="$test_root/repository" RESTIC_PASSWORD_FILE="$test_root/restic-password" \
  "$RESTIC_BIN" init
# restore.sh refuses to run on a target that was never bootstrapped (the marker
# is written only by install-vm.sh). This machine is the developer's own, so skip
# that one check explicitly instead of faking the marker.
export AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true

# CI builds this image beforehand with a shared layer cache and sets the variable.
if [[ ${AUTOBOT_RESTORE_TEST_SKIP_BUILD:-false} != true ]]; then
  docker build -q -t autobot:restore-test -f apps/backend/Dockerfile apps/backend >/dev/null
fi
docker tag autobot:restore-test "ghcr.io/example-owner/autobot:$sha"
source_compose() { compose_in "$source_dir" "$source_project" "$@"; }
(
  source_compose up -d db >/dev/null
  source_compose run --rm web-panel \
    python manage.py migrate --noinput >/dev/null
  source_compose run --rm web-panel \
    python manage.py apply_grants >/dev/null
  source_compose run --rm web-panel \
    python manage.py tenant_config validate --all >/dev/null
  source_compose run --rm web-panel \
    python manage.py seed_demos >/dev/null
  source_compose exec -T db \
    psql -U postgres -d autobot -v ON_ERROR_STOP=1 -q -c \
    "INSERT INTO contact (id, tenant_id, channel, external_id, created_at) VALUES ('00000000-0000-7000-8000-000000000001', (SELECT id FROM tenant WHERE slug='demo-autobuses'), 'test', 'local-fixture', now())" >/dev/null
  # A channel secret encrypted with the source's SECRETS_ENCRYPTION_KEY: after the
  # restore, the key that travelled in the backed-up .env must still decrypt it.
  source_compose run --rm web-panel \
    python manage.py shell -c "
from autobot.tenancy.crypto import encrypt
from autobot.tenancy.models import Tenant, TenantSecret
tenant = Tenant.objects.using('owner').get(slug='demo-autobuses')
TenantSecret.objects.using('owner').update_or_create(
    tenant=tenant,
    defaults={'channel_type': 'telegram', 'ciphertext': encrypt({'token': 'restore-fixture'}), 'updated_by': 'restore-test'},
)
" >/dev/null
)
counts() {
  compose_in "$2" "$1" exec -T db \
    psql -U postgres -d autobot -At -c \
    'SELECT t.slug, count(c.id) FROM tenant t LEFT JOIN contact c ON c.tenant_id=t.id GROUP BY t.slug ORDER BY t.slug'
}
before=$(counts "$source_project" "$source_dir")
(cd "$source_dir" && AUTOBOT_PROJECT="$source_project" deploy/scripts/backup.sh)
# Without the key restore.sh must refuse, clearly, before touching the target...
if (cd "$target_dir" && AUTOBOT_PROJECT="$target_project" AUTOBOT_RESTORE_DB_ONLY=true \
  deploy/scripts/restore.sh --confirm-empty-target >/dev/null 2>"$test_root/no-key.err"); then
  echo 'restore.sh succeeded without the encryption key' >&2
  exit 1
fi
grep -q 'AUTOBOT_SECRETS_KEY_FILE' "$test_root/no-key.err" || {
  echo 'restore.sh did not explain how to give the encryption key' >&2
  exit 1
}
# ...and a WRONG key must be caught by the decryption check, not restored "fine".
wrong_key=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
if (cd "$target_dir" && AUTOBOT_PROJECT="$target_project" AUTOBOT_RESTORE_DB_ONLY=true \
  SECRETS_ENCRYPTION_KEY="$wrong_key" deploy/scripts/restore.sh --confirm-empty-target >/dev/null 2>&1); then
  echo 'restore.sh accepted a wrong encryption key' >&2
  exit 1
fi
(cd "$target_dir" && AUTOBOT_PROJECT="$target_project" AUTOBOT_RESTORE_DB_ONLY=true \
  AUTOBOT_SECRETS_KEY_FILE="$test_root/secrets-key" \
  deploy/scripts/restore.sh --confirm-empty-target)
# The snapshot itself must not carry the key; the restored .env must have it back.
if grep -q "$secrets_key" "$target_dir/var/backups/autobot.env" 2>/dev/null; then
  echo 'The staged backup .env contains the encryption key' >&2
  exit 1
fi
grep -q "^SECRETS_ENCRYPTION_KEY=$secrets_key\$" "$target_dir/.env" || {
  echo 'The restored .env does not have the given encryption key' >&2
  exit 1
}
after=$(counts "$target_project" "$target_dir")
if [[ $before != "$after" || $before != *'demo-autobuses|1'* ]]; then
  echo 'Per-tenant counts differ after restore' >&2
  exit 1
fi
# restore.sh reapplies roles and permissions (pg_restore --no-acl drops them).
grants=$(compose_in "$target_dir" "$target_project" \
  exec -T db psql -U postgres -d autobot -At -c \
  "SELECT has_table_privilege('fp_app', 'tenant', 'INSERT'), has_table_privilege('fp_readonly', 'auth_user', 'SELECT')")
if [[ $grants != 'f|f' ]]; then
  echo "Permissions were not reapplied after restore: $grants" >&2
  exit 1
fi

# Verify the restore for real, not just the rows: start the restored `web` on the
# restored database (no workers, no Caddy) and check that (a) /health/internal
# answers with every tenant readable and (b) the SECRETS_ENCRYPTION_KEY restored
# from the backed-up .env decrypts the restored tenant_secret rows. Both are what
# would fail on a real recovery if the key or the registry did not survive.
web_port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
target_compose() {
  AUTOBOT_WEB_HOST_PORT="$web_port" SHA="$sha" compose_in "$target_dir" "$target_project" "$@"
}
target_compose up -d --no-deps web >/dev/null
healthy=false
for ((i=0; i<30; i++)); do
  if response=$(curl --silent --fail --max-time 2 "http://127.0.0.1:$web_port/health/internal" 2>/dev/null) &&
    python3 -c 'import json, sys
r = json.load(sys.stdin)
assert r["status"] == "ok" and r["tenants"]["unreadable"] == 0 and r["tenants"]["loaded"] >= 1' <<<"$response" 2>/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ $healthy != true ]]; then
  echo "Restored web did not report healthy with every tenant readable: ${response:-no answer}" >&2
  target_compose logs --tail=50 web >&2 || true
  exit 1
fi
decrypted=$(target_compose run --rm -T web-panel python manage.py shell -c "
from autobot.tenancy.crypto import decrypt
from autobot.tenancy.models import TenantSecret
count = 0
for secret in TenantSecret.objects.using('owner'):
    decrypt(bytes(secret.ciphertext))
    count += 1
print('decrypted', count)
") || {
  echo 'The restored encryption key could not decrypt the restored tenant_secret rows' >&2
  exit 1
}
# `manage.py shell` also prints log lines and Django's auto-import notice to stdout:
# keep only the last line, the one the snippet printed.
decrypted=${decrypted##*$'\n'}
if [[ $decrypted != 'decrypted '[1-9]* ]]; then
  echo "Expected at least one decryptable tenant_secret after the restore, got: $decrypted" >&2
  exit 1
fi
echo "Local restore verified: $after; $decrypted secret(s) decrypted; /health/internal ok"
