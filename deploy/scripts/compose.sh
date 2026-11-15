#!/usr/bin/env bash
# Run an arbitrary `docker compose` command against the deployed image, with the
# root .env and the last deployed SHA already wired in (A2): `docker compose exec
# web ...` run by hand would otherwise fail on the unset ${SHA:?...} substitution.
# Invoked by the operator on the VPS, or via `make prod-compose HOST=... ARGS="..."`.
set -euo pipefail
# shellcheck source=./lib.sh
source "$(dirname "$0")/lib.sh"
exec "${compose[@]}" "$@"
