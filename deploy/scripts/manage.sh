#!/usr/bin/env bash
# Run manage.py with the deployed image, in `web-panel`: the only service with the
# fp_owner credential that operation commands (panel_user, tenant_purge...) need
# (ADR-020). Invoked by the operator on the VPS.
set -euo pipefail
# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
tty=(-T)
[[ -t 0 ]] && tty=()
exec "${compose[@]}" run --rm "${tty[@]}" web-panel python manage.py "$@"
