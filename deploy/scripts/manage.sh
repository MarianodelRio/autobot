#!/usr/bin/env bash
# Run manage.py with the deployed image. Invoked by the operator on the VPS.
set -euo pipefail
# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
tty=(-T)
[[ -t 0 ]] && tty=()
exec "${compose[@]}" run --rm "${tty[@]}" web python manage.py "$@"
