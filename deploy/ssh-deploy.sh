#!/usr/bin/env bash
# Forced command for the CI key in deploy's authorized_keys.
set -euo pipefail
original=${SSH_ORIGINAL_COMMAND:-}
if [[ ! $original =~ ^deploy/deploy[.]sh[[:space:]]([0-9a-f]{40})$ ]]; then
  echo 'Only a full-SHA deployment is allowed with this key' >&2
  exit 2
fi
sha=${BASH_REMATCH[1]}
cd /srv/autobot
git diff --quiet
git diff --cached --quiet
git fetch --quiet origin main
git merge-base --is-ancestor "$sha" origin/main
git cat-file -e "$sha:deploy/deploy.sh"
git cat-file -e "$sha:compose.prod.yaml"
git checkout --quiet --detach "$sha"
exec /srv/autobot/deploy/deploy.sh "$sha"
