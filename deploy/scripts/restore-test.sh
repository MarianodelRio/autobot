#!/usr/bin/env bash
# Disposable local backup/restore exercise; needs Docker and restic, no real services.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${RESTIC_BIN:=restic}"
command -v "$RESTIC_BIN" >/dev/null
test_root=$(mktemp -d)
source_dir=$test_root/source
target_dir=$test_root/target
for dir in "$source_dir" "$target_dir"; do
  mkdir -p "$dir/deploy/compose" "$dir/deploy/postgres" "$dir/deploy/caddy" "$dir/deploy/scripts" \
    "$dir/var"
  # Like bootstrap-server.sh on the real VPS: pre-create the bind-mount source so
  # Docker never auto-creates it as root when a container starts before backup.sh
  # does (`var/state/ops` is mounted read-only into web/worker).
  mkdir -p "$dir/var/state/ops"
done
sha=$(python3 -c 'import secrets; print(secrets.token_hex(20))')
source_project="fp-restore-src-${sha:0:8}"
target_project="fp-restore-dst-${sha:0:8}"
ping_pid=''
cleanup() {
  if [[ -n $ping_pid ]]; then
    kill "$ping_pid" >/dev/null 2>&1 || true
  fi
  (cd "$source_dir" && docker compose --project-name "$source_project" \
    -f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml --env-file .env \
    down -v) >/dev/null 2>&1 || true
  (cd "$target_dir" && docker compose --project-name "$target_project" \
    -f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml --env-file .env \
    down -v) >/dev/null 2>&1 || true
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
cat >"$source_dir/.env" <<EOF
ENVIRONMENT=prod
PUBLIC_HOST=localhost
SHA=$sha
AUTOBOT_IMAGE=ghcr.io/example-owner/autobot
AUTOBOT_PANEL_IMAGE=ghcr.io/example-owner/autobot-panel
DEPLOY_UID=$(id -u)
DJANGO_SECRET_KEY=local-restore-test-only
SECRETS_ENCRYPTION_KEY=$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
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
# A3: backup.sh never runs `restic init` itself; do it once here, like the
# operator does by hand on a real server, and record the repository's id the
# same way the first real backup would (so backup.sh's id check doesn't trip).
RESTIC_REPOSITORY="$test_root/repository" RESTIC_PASSWORD_FILE="$test_root/restic-password" \
  "$RESTIC_BIN" init
# T1: restore.sh refuses to run on a target that was never bootstrapped (the marker
# is written only by install-vm.sh). This machine is the developer's own, so skip
# that one check explicitly instead of faking the marker.
export AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true

docker build -q -t autobot:restore-test -f apps/backend/Dockerfile apps/backend >/dev/null
docker tag autobot:restore-test "ghcr.io/example-owner/autobot:$sha"
# --env-file is relative: every use below `cd`s into source_dir or target_dir first
# (A1: compose's own .env lookup is relative to deploy/compose/, not the cwd).
compose_args=(-f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml --env-file .env)
(
  cd "$source_dir"
  docker compose --project-name "$source_project" "${compose_args[@]}" up -d db >/dev/null
  docker compose --project-name "$source_project" "${compose_args[@]}" run --rm web \
    python manage.py migrate --noinput >/dev/null
  docker compose --project-name "$source_project" "${compose_args[@]}" run --rm web \
    python manage.py apply_grants >/dev/null
  docker compose --project-name "$source_project" "${compose_args[@]}" run --rm web \
    python manage.py tenant_config validate --all >/dev/null
  docker compose --project-name "$source_project" "${compose_args[@]}" run --rm web \
    python manage.py seed_demos >/dev/null
  docker compose --project-name "$source_project" "${compose_args[@]}" exec -T db \
    psql -U postgres -d autobot -v ON_ERROR_STOP=1 -q -c \
    "INSERT INTO contact (id, tenant_id, channel, external_id, created_at) VALUES ('00000000-0000-7000-8000-000000000001', (SELECT id FROM tenant WHERE slug='demo-autobuses'), 'test', 'local-fixture', now())" >/dev/null
  # A channel secret encrypted with the source's SECRETS_ENCRYPTION_KEY: after the
  # restore, the key that travelled in the backed-up .env must still decrypt it.
  docker compose --project-name "$source_project" "${compose_args[@]}" run --rm web \
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
  local project=$1 dir=$2
  (cd "$dir" && docker compose --project-name "$project" "${compose_args[@]}" exec -T db \
    psql -U postgres -d autobot -At -c \
    'SELECT t.slug, count(c.id) FROM tenant t LEFT JOIN contact c ON c.tenant_id=t.id GROUP BY t.slug ORDER BY t.slug')
}
before=$(counts "$source_project" "$source_dir")
(cd "$source_dir" && AUTOBOT_PROJECT="$source_project" deploy/scripts/backup.sh)
(cd "$target_dir" && AUTOBOT_PROJECT="$target_project" AUTOBOT_RESTORE_DB_ONLY=true \
  deploy/scripts/restore.sh --confirm-empty-target)
after=$(counts "$target_project" "$target_dir")
if [[ $before != "$after" || $before != *'demo-autobuses|1'* ]]; then
  echo 'Per-tenant counts differ after restore' >&2
  exit 1
fi
# restore.sh reapplies roles and permissions (pg_restore --no-acl drops them).
grants=$(cd "$target_dir" && docker compose --project-name "$target_project" "${compose_args[@]}" \
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
  (cd "$target_dir" && AUTOBOT_WEB_HOST_PORT="$web_port" SHA="$sha" \
    docker compose --project-name "$target_project" "${compose_args[@]}" "$@")
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
decrypted=$(target_compose run --rm -T web python manage.py shell -c "
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
if [[ $decrypted != 'decrypted '[1-9]* ]]; then
  echo "Expected at least one decryptable tenant_secret after the restore, got: $decrypted" >&2
  exit 1
fi
echo "Local restore verified: $after; $decrypted secret(s) decrypted; /health/internal ok"
