#!/usr/bin/env bash
# Run manage.py with the deployed image. Invoked by the operator on the VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
SHA=$(cat .deployed-sha)
export SHA
tty=(-T)
[[ -t 0 ]] && tty=()
exec docker compose --project-name autobot -f compose.prod.yaml run --rm "${tty[@]}" web python manage.py "$@"
