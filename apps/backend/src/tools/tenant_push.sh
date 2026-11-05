#!/usr/bin/env bash
# Export local config and stream it to the deployed CLI, optionally carrying secrets.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
umask 077
slug=${SLUG:-}
target_host=${HOST:?Set HOST}
secret_file=${SECRETS:-}
if [[ ! $slug =~ ^[a-z0-9]+(-[a-z0-9]+)*$ || ${#slug} -gt 64 ]]; then
  echo 'SLUG must be a valid business slug' >&2
  exit 2
fi
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
uv run --project apps/backend python apps/backend/manage.py tenant_config export "$slug" "$temporary"
if [[ -n $secret_file ]]; then
  uv run --project apps/backend python - "$secret_file" "$slug" "$temporary/secrets.yaml" <<'PY'
import os
import sys
from pathlib import Path

import yaml

try:
    data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    selected = data[sys.argv[2]]
    if not isinstance(selected, dict):
        raise ValueError()
except (OSError, UnicodeError, yaml.YAMLError, TypeError, KeyError, ValueError):
    raise SystemExit("No valid secrets entry for SLUG") from None
with os.fdopen(os.open(sys.argv[3], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
    yaml.safe_dump({sys.argv[2]: selected}, output)
PY
fi
tar -C "$temporary" -cz . | ssh "deploy@$target_host" \
  /srv/autobot/deploy/scripts/manage.sh tenant_config import - --comment push
