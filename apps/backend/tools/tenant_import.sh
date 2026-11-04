#!/usr/bin/env bash
# Import a local directory using the host's local database connection.
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${DIR:?Set DIR to the tenant directory}"
arguments=(tenant_config import "$DIR" --comment 'Local import')
if [[ -n ${SECRETS:-} ]]; then
  arguments+=(--secrets "$SECRETS")
fi
exec uv run python manage.py "${arguments[@]}"
