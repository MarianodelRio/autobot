#!/usr/bin/env bash
# Run from the host timer as deploy (A11): every deploy leaves the previous image
# behind (needed for an instant rollback) and dangling layers from failed pulls;
# left unchecked, the 40 GB disk a small VPS has fills up over time.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Keeps anything still referenced by a container and anything pulled in the last
# day, so a deploy in progress is never affected. An older, unreferenced image
# (the previous SHA's, once it's no longer the one running) is removed; a rollback
# past that point re-pulls it, same as any other image `up` doesn't find locally.
docker image prune --all --force --filter 'until=24h'
