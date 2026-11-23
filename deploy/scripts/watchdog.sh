#!/usr/bin/env bash
# Host watchdog, run every 5 minutes by autobot-watchdog.timer as deploy. It must work
# when everything else is broken, so it depends only on bash, curl, df and docker: no
# Django, no database, no worker, no panel. It talks to Telegram directly, with the same
# bot and chat as the ops alerts (NOTIFY_BOT_TOKEN and OPS_TELEGRAM_CHAT_ID in .env).
#
# Conditions (each alerts once per AUTOBOT_WATCHDOG_REPEAT_SECS, 1 h by default, and once
# more when it clears):
#   disk   less than 100 - AUTOBOT_WATCHDOG_DISK_PCT (10) % of the filesystem is available
#          to the deploy user (f_bavail, which excludes root's reserved blocks)
#   db     the db container is missing, stopped or not healthy
#   stale  var/state/ops/containers.json (written every minute by containers.sh) is older
#          than AUTOBOT_WATCHDOG_STALE_MIN (15) minutes: the host timers, Docker or the
#          disk are broken. Nothing on disk records the last ops_check run (its heartbeat
#          goes straight to Healthchecks), so a stuck worker is that external check's job.
# While a deploy or a restore is running (the same signals containers.sh uses) the db and
# stale checks are skipped: a recreated db or a pause in snapshots is expected then.
set -euo pipefail
cd "$(dirname "$0")/../.."
umask 077
state_dir=var/state/watchdog
mkdir -p "$state_dir"

disk_pct=${AUTOBOT_WATCHDOG_DISK_PCT:-90}
stale_min=${AUTOBOT_WATCHDOG_STALE_MIN:-15}
repeat=${AUTOBOT_WATCHDOG_REPEAT_SECS:-3600}
project=${AUTOBOT_PROJECT:-autobot}
now=$(date +%s)
host=$(hostname 2>/dev/null || echo server)

# Read the two values from .env without sourcing it (it is data here, not code).
env_value() {
  local line
  line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?$1=" .env 2>/dev/null | tail -n 1) || return 0
  line=${line#*=}
  line=${line%%[[:space:]]#*}
  line=${line//\"/}
  line=${line//\'/}
  printf '%s' "$line" | tr -d '[:space:]'
}
token=${NOTIFY_BOT_TOKEN:-$(env_value NOTIFY_BOT_TOKEN)}
chat=${OPS_TELEGRAM_CHAT_ID:-$(env_value OPS_TELEGRAM_CHAT_ID)}
if [[ -z $token || -z $chat ]]; then
  echo 'NOTIFY_BOT_TOKEN or OPS_TELEGRAM_CHAT_ID is not set in .env: the watchdog cannot alert' >&2
  exit 0
fi

# The token travels on stdin (curl --config -), never in the arguments, where `ps` would
# show it, and is never printed. A failure leaves the state untouched: retried next run.
send() {
  printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
    curl --config - --silent --fail --max-time 10 --output /dev/null \
      --data-urlencode "chat_id=$chat" \
      --data-urlencode "text=$1" 2>/dev/null
}

# alert NAME TEXT: send at most once per $repeat while the condition holds.
alert() {
  local name=$1 last=0
  [[ -f $state_dir/$name ]] && last=$(cat "$state_dir/$name" 2>/dev/null || echo 0)
  [[ $last =~ ^[0-9]+$ ]] || last=0
  ((now - last >= repeat)) || return 0
  if send "🔴 [$host] $2"; then
    printf '%s\n' "$now" >"$state_dir/$name"
  else
    echo "Could not send the $name alert to Telegram" >&2
  fi
}

# ok NAME TEXT: the condition cleared; say so once, only if it had been reported.
ok() {
  [[ -f $state_dir/$1 ]] || return 0
  if send "🟢 [$host] $2"; then
    rm -f "$state_dir/$1"
  else
    echo "Could not send the $1 recovery to Telegram" >&2
  fi
}

# --- disk ---------------------------------------------------------------------------
read -r avail size < <(df --output=avail,size -B1 . | tail -n 1) || true
if [[ ${avail:-} =~ ^[0-9]+$ && ${size:-} =~ ^[0-9]+$ ]] && ((size > 0)); then
  used=$((100 - avail * 100 / size))
  if ((used > disk_pct)); then
    alert disk "Disco al ${used}% (umbral ${disk_pct}%): libera espacio antes de que fallen los backups y la base de datos"
  else
    ok disk "Disco recuperado (${used}% usado)"
  fi
else
  echo 'Could not read disk usage from df' >&2
fi

# --- maintenance: expected unavailability, not an incident ----------------------------
if [[ -f var/.restore-incomplete || -f var/.frozen ]] || ! flock -n -s var/.deploy.lock true 2>/dev/null; then
  exit 0
fi

# --- db -------------------------------------------------------------------------------
db_status=missing
db_id=$(docker ps -aq --filter "label=com.docker.compose.project=$project" \
  --filter "label=com.docker.compose.service=db" 2>/dev/null | head -n 1) || db_id=
if [[ -n $db_id ]]; then
  db_status=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$db_id" 2>/dev/null) || db_status=unknown
fi
if [[ $db_status == running/healthy ]]; then
  ok db 'La base de datos vuelve a estar sana'
else
  alert db "El contenedor db no está sano (estado: $db_status): revisa docker compose ps y los logs"
fi

# --- stale host snapshot ----------------------------------------------------------------
snapshot=var/state/ops/containers.json
mtime=$(stat -c %Y "$snapshot" 2>/dev/null || echo 0)
if ((now - mtime > stale_min * 60)); then
  alert stale "var/state/ops/containers.json no se actualiza desde hace más de ${stale_min} min: fallan los timers del host, Docker o el disco"
else
  ok stale 'El estado del host vuelve a actualizarse'
fi
