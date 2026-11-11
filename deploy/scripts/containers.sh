#!/usr/bin/env bash
# Run from the host timer as deploy; writes a safelisted container snapshot that
# web, worker-inbound and worker-outbound mount read-only (:ro). No container ever
# touches docker.sock: this script runs on the host, not inside a container.
set -euo pipefail
cd "$(dirname "$0")/../.."
umask 077
mkdir -p var/state/ops

project=${AUTOBOT_PROJECT:-autobot}

maintenance=""
if [[ -f var/.restore-incomplete ]]; then
  maintenance=restore
# Shared, non-blocking probe: deploy.sh holds this lock exclusively for the whole
# deployment, so failing to get it here just means one is in progress.
elif ! flock -n -s var/.deploy.lock true 2>/dev/null; then
  maintenance=deploy
fi

# oneoff=False excludes `docker compose run --rm` containers (prod-manage,
# migrations…), which are not services.
ids=$(docker ps -aq \
  --filter "label=com.docker.compose.project=$project" \
  --filter "label=com.docker.compose.oneoff=False")

template='[{{json .Name}},{{json (index .Config.Labels "com.docker.compose.service")}},{{json .State.Status}},{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}},{{json .RestartCount}},{{json .State.OOMKilled}},{{json .State.ExitCode}},{{json .State.StartedAt}},{{json .State.FinishedAt}},{{json .Config.Image}}]'
lines=""
if [[ -n $ids ]]; then
  # shellcheck disable=SC2086 # ids are container ids (newline-separated, no spaces)
  lines=$(docker inspect --format "$template" $ids)
fi

tmp=$(mktemp var/state/ops/.containers.json.XXXXXXXX)
# A failure below would otherwise leave one temp file behind per minute.
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$lines" | python3 -I -c '
import json
import sys
from datetime import UTC, datetime

project, maintenance = sys.argv[1], sys.argv[2] or None


def iso(value):
    if not isinstance(value, str) or value.startswith("0001-"):
        return None
    return value[:19] + "Z"


containers = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    name, service, status, health, restart_count, oom_killed, exit_code, started_at, finished_at, image = (
        json.loads(line)
    )
    containers.append(
        {
            "name": name.removeprefix("/"),
            "service": service,
            "status": status,
            "health": health,
            "restart_count": restart_count,
            "oom_killed": oom_killed,
            "exit_code": exit_code,
            "started_at": iso(started_at),
            "finished_at": iso(finished_at),
            "image": image,
        }
    )
containers.sort(key=lambda c: (c["service"], c["name"]))
doc = {
    "version": 1,
    "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "project": project,
    "maintenance": maintenance,
    "containers": containers,
}
json.dump(doc, sys.stdout)
' "$project" "$maintenance" >"$tmp"
mv "$tmp" var/state/ops/containers.json
