#!/usr/bin/env bash
# Disposable local backup/restore exercise; needs Docker and restic, no real services.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${RESTIC_BIN:=restic}"
command -v "$RESTIC_BIN" >/dev/null
test_root=$(mktemp -d)
source_dir=$test_root/source
target_dir=$test_root/target
mkdir -p "$source_dir/deploy/postgres" "$target_dir/deploy/postgres"
sha=$(python3 -c 'import secrets; print(secrets.token_hex(20))')
source_project="fp-restore-src-${sha:0:8}"
target_project="fp-restore-dst-${sha:0:8}"
ping_pid=''
cleanup() {
  if [[ -n $ping_pid ]]; then
    kill "$ping_pid" >/dev/null 2>&1 || true
  fi
  (cd "$source_dir" && docker compose --project-name "$source_project" -f compose.prod.yaml down -v) >/dev/null 2>&1 || true
  (cd "$target_dir" && docker compose --project-name "$target_project" -f compose.prod.yaml down -v) >/dev/null 2>&1 || true
  docker image rm "ghcr.io/marianodelrio/autobot:$sha" >/dev/null 2>&1 || true
  rm -rf "$test_root"
}
trap cleanup EXIT

for dir in "$source_dir" "$target_dir"; do
  cp compose.prod.yaml Caddyfile "$dir/"
  cp deploy/postgres/init-roles.sh "$dir/deploy/postgres/"
  cp deploy/backup.sh deploy/restore.sh "$dir/deploy/"
done
cat >"$source_dir/.env" <<EOF
ENVIRONMENT=prod
PUBLIC_HOST=localhost
SHA=$sha
DEPLOY_UID=$(id -u)
DJANGO_SECRET_KEY=local-restore-test-only
DJANGO_ALLOWED_HOSTS=localhost
DB_APP_URL=postgres://fp_app:local@db:5432/autobot
DB_OWNER_URL=postgres://fp_owner:local@db:5432/autobot
POSTGRES_PASSWORD=local
FP_OWNER_PASSWORD=local
FP_APP_PASSWORD=local
EOF
printf '{}\n' >"$source_dir/secrets.yaml"
printf '{}\n' >"$source_dir/google_sa.json"
printf '%s\n' "$sha" >"$source_dir/.deployed-sha"
printf '%s\n' local-restore-password >"$test_root/restic-password"
chmod 600 "$source_dir/.env" "$source_dir/secrets.yaml" \
  "$source_dir/google_sa.json" "$test_root/restic-password"
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
"$RESTIC_BIN" -r "$test_root/repository" --password-file "$test_root/restic-password" init >/dev/null

docker build -q -t autobot:restore-test . >/dev/null
docker tag autobot:restore-test "ghcr.io/marianodelrio/autobot:$sha"
(
  cd "$source_dir"
  docker compose --project-name "$source_project" -f compose.prod.yaml up -d db >/dev/null
  docker compose --project-name "$source_project" -f compose.prod.yaml run --rm web \
    python manage.py migrate --noinput >/dev/null
  docker compose --project-name "$source_project" -f compose.prod.yaml run --rm web \
    python manage.py sync_tenants --strict >/dev/null
  docker compose --project-name "$source_project" -f compose.prod.yaml exec -T db \
    psql -U postgres -d autobot -v ON_ERROR_STOP=1 -q -c \
    "INSERT INTO contact (id, tenant_id, channel, external_id, created_at) VALUES ('00000000-0000-7000-8000-000000000001', '01a163fd-bed0-7002-80df-8f2acdc7778b', 'test', 'local-fixture', now())" >/dev/null
)
counts() {
  local project=$1 dir=$2
  (cd "$dir" && docker compose --project-name "$project" -f compose.prod.yaml exec -T db \
    psql -U postgres -d autobot -At -c \
    'SELECT t.slug, count(c.id) FROM tenant t LEFT JOIN contact c ON c.tenant_id=t.id GROUP BY t.slug ORDER BY t.slug')
}
before=$(counts "$source_project" "$source_dir")
(cd "$source_dir" && AUTOBOT_PROJECT="$source_project" deploy/backup.sh)
(cd "$target_dir" && AUTOBOT_PROJECT="$target_project" AUTOBOT_RESTORE_DB_ONLY=true \
  deploy/restore.sh --confirm-empty-target)
after=$(counts "$target_project" "$target_dir")
if [[ $before != "$after" || $before != *'autocares-ss|1'* ]]; then
  echo 'Per-tenant counts differ after restore' >&2
  exit 1
fi
echo "Local restore verified: $after"
