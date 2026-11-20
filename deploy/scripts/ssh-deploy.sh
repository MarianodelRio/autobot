#!/usr/bin/env bash
# Forced command for the CI key in deploy's authorized_keys (installed by
# install-vm.sh): `restrict,command=".../ssh-deploy.sh"`. The only thing it lets
# through is `deploy/scripts/deploy.sh <full-sha>` of a commit that is on `main`.
set -euo pipefail
original=${SSH_ORIGINAL_COMMAND:-}
if [[ ! $original =~ ^deploy/scripts/deploy[.]sh[[:space:]]([0-9a-f]{40})$ ]]; then
  echo 'Only a full-SHA deployment is allowed with this key' >&2
  exit 2
fi
sha=${BASH_REMATCH[1]}
# The checkout lives in the script's own location (/srv/autobot on the VM).
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root"
# Take deploy.sh's lock *before* touching the working tree: a second SSH deploy (or
# one by hand) must not `git checkout` underneath a deploy that is running. The lock
# is handed on to deploy.sh through AUTOBOT_DEPLOY_LOCK_HELD, which makes it skip its
# own flock (a second flock on the same file from the same process tree would block
# against this one).
mkdir -p var
exec 9>var/.deploy.lock
flock -w 10 9 || { echo 'Another deployment is running' >&2; exit 1; }
export AUTOBOT_DEPLOY_LOCK_HELD=1
git diff --quiet
git diff --cached --quiet
git fetch --quiet origin main
git merge-base --is-ancestor "$sha" origin/main
git cat-file -e "$sha:deploy/scripts/deploy.sh"
git cat-file -e "$sha:deploy/compose/compose.prod.yaml"
git checkout --quiet --detach "$sha"
exec "$root/deploy/scripts/deploy.sh" "$sha"
