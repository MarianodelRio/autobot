#!/usr/bin/env bash
# Installs Autobot on an Ubuntu 24.04 VM, from a clone of the repository *inside* the
# VM (ADR-017). One command, run as root or with sudo, idempotent and resumable:
#
#   sudo deploy/scripts/install-vm.sh --public-host api.example.com \
#     --google-sa ./google_sa.json [--env-file ./install.env]
#
# Steps, in order (each checks first whether it is already done):
#   ci-key      generate the CI deploy key (ed25519) the GitHub workflow will use
#   base        packages, Docker, swap, users `deploy`/`admin`, the /srv/autobot
#               checkout, the systemd timers (bootstrap-server.sh --base)
#   env         /srv/autobot/.env (ensure-env.sh), google_sa.json, optional externals
#   deploy      the first deployment of this commit, through ssh-deploy.sh
#   health      read-only checks of the whole stack
#   harden-ssh  ufw + sshd hardening (bootstrap-server.sh --harden-ssh), only after an
#               explicit confirmation that a second session works
#   marker      /var/lib/autobot/bootstrap-complete, the marker restore.sh requires
#   github      optional: set the `production` environment's secrets with `gh`
# and, always at the end, a summary of what is still manual.
#
# It never invents a credential: every external value (Telegram, Sentry, Healthchecks,
# restic, the Google service account) comes from the operator or stays pending. It
# never runs `restic init`.
#
# Options: see --help. `--check` changes nothing and reports each step.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
srv=/srv/autobot
state_dir=/var/lib/autobot
base_marker=$state_dir/bootstrap-base-complete
sshd_marker=$state_dir/bootstrap-sshd-complete
bootstrap_marker=$state_dir/bootstrap-complete
ci_private=/root/autobot-ci-deploy-key
ci_public=$state_dir/ci-deploy.pub

all_steps=(ci-key base env deploy health harden-ssh marker github)

# --- helpers (also sourced by tests with AUTOBOT_INSTALL_LIB_ONLY=1) ---------------

say() { printf '%s\n' "$*"; }
warn() { printf 'AVISO: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Values written to .env are sourced by bash (ensure-env.sh) and parsed by compose:
# only a conservative alphabet is accepted, so nothing can break out of the line.
safe_env_value() { [[ $1 =~ ^[A-Za-z0-9_.:/@%+=,~-]*$ ]]; }

# https://github.com/<owner>/<repo>[.git] from either remote style.
normalize_repo_url() {
  local url=$1
  if [[ $url =~ ^git@github\.com:(.+)$ ]]; then
    url="https://github.com/${BASH_REMATCH[1]}"
  elif [[ $url =~ ^ssh://git@github\.com/(.+)$ ]]; then
    url="https://github.com/${BASH_REMATCH[1]}"
  fi
  [[ $url == *.git ]] || url="$url.git"
  [[ $url =~ ^https://[A-Za-z0-9.-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.git$ ]] || return 1
  printf '%s\n' "$url"
}

# owner/repo from a normalized URL.
repo_slug() {
  local url=${1%.git}
  printf '%s\n' "${url#https://*/}"
}

# Last value of KEY in an env file (ensure-env.sh appends, so the last one wins).
env_get() {
  local file=$1 key=$2
  [[ -f $file ]] || return 0
  { grep "^${key}=" "$file" || true; } | tail -n 1 | cut -d= -f2-
}

# Replace (or add) KEY=VALUE keeping the file's owner and mode.
env_set() {
  local file=$1 key=$2 value=$3 tmp
  safe_env_value "$value" || die "El valor de $key tiene caracteres no permitidos en .env"
  tmp=$(mktemp)
  { grep -v "^${key}=" "$file" 2>/dev/null || true; } >"$tmp"
  printf '%s=%s\n' "$key" "$value" >>"$tmp"
  cat "$tmp" >"$file"
  rm -f "$tmp"
}

usage() {
  cat <<'EOF'
Uso: sudo deploy/scripts/install-vm.sh [opciones]

  --public-host HOST     nombre público (p. ej. api.example.com); obligatorio la primera vez
  --operator-key FILE    clave PÚBLICA SSH del operador (la de admin y deploy). Por defecto, la
                         única clave de ~/.ssh/authorized_keys del usuario que ejecuta sudo
  --google-sa FILE       cuenta de servicio de Google (se instala en var/google_sa.json)
  --no-google-sa         instala un var/google_sa.json vacío (Calendar no funcionará hasta
                         subir el real)
  --env-file FILE        KEY=VALUE con credenciales externas opcionales (Telegram, Sentry,
                         Healthchecks, restic...); solo se aceptan claves conocidas
  --image-owner OWNER    propietario en GHCR (por defecto, el de la URL del repositorio)
  --repo-url URL         por defecto, el origin de este clon
  --sha SHA              commit a desplegar (por defecto, HEAD de este clon; debe estar en
                         origin/main y con su imagen ya publicada por el CI)
  --restore-target       prepara la VM solo para restaurar un backup (sin .env ni despliegue);
                         lo que espera server-migrate.sh y restaurar.md
  --rotate-ci-key        genera una clave de CI nueva (la anterior deja de valer)
  --yes                  no pregunta nada. Incluido endurecer SSH: úsalo solo si YA has abierto
                         otra sesión como admin@ y deploy@ con tu clave
  --only PASO            ejecuta solo ese paso (repetible)
  --skip PASO            omite ese paso (repetible o separado por comas)
  --check                no cambia nada: informa de qué pasos están hechos
  -h, --help             esta ayuda

Pasos: ci-key base env deploy health harden-ssh marker github
EOF
}

# --- when sourced by tests, stop here ------------------------------------------------
if [[ ${AUTOBOT_INSTALL_LIB_ONLY:-} == 1 ]]; then
  # shellcheck disable=SC2317  # `exit` is the fallback when executed, not sourced.
  return 0 2>/dev/null || exit 0
fi

# --- arguments ---------------------------------------------------------------------

public_host=''
operator_key_file=''
google_sa=''
no_google_sa=false
env_file=''
image_owner=''
image_owner_given=false
repo_url=''
sha=''
restore_target=false
rotate_ci_key=false
assume_yes=false
check_only=false
only_steps=()
skip_steps=()
original_args=("$@")

valid_step() {
  local step
  for step in "${all_steps[@]}"; do [[ $step == "$1" ]] && return 0; done
  return 1
}

while (($#)); do
  case $1 in
  --public-host) public_host=${2:?--public-host needs a value}; shift 2 ;;
  --operator-key) operator_key_file=${2:?--operator-key needs a file}; shift 2 ;;
  --google-sa) google_sa=${2:?--google-sa needs a file}; shift 2 ;;
  --no-google-sa) no_google_sa=true; shift ;;
  --env-file) env_file=${2:?--env-file needs a file}; shift 2 ;;
  --image-owner) image_owner=${2:?--image-owner needs a value}; image_owner_given=true; shift 2 ;;
  --repo-url) repo_url=${2:?--repo-url needs a value}; shift 2 ;;
  --sha) sha=${2:?--sha needs a value}; shift 2 ;;
  --restore-target) restore_target=true; shift ;;
  --rotate-ci-key) rotate_ci_key=true; shift ;;
  --yes) assume_yes=true; shift ;;
  --check) check_only=true; shift ;;
  --only)
    valid_step "${2:-}" || { echo "Paso desconocido: ${2:-}" >&2; usage >&2; exit 2; }
    only_steps+=("$2"); shift 2 ;;
  --skip)
    IFS=, read -r -a extra <<<"${2:-}"
    for step in "${extra[@]}"; do
      valid_step "$step" || { echo "Paso desconocido: $step" >&2; usage >&2; exit 2; }
      skip_steps+=("$step")
    done
    shift 2 ;;
  -h | --help) usage; exit 0 ;;
  *) echo "Opción desconocida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $restore_target == true ]]; then
  skip_steps+=(env deploy health github)
fi
if [[ -n $public_host && ! $public_host =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "--public-host no es un nombre de host válido: $public_host" >&2
  exit 2
fi
if [[ -n $sha && ! $sha =~ ^[0-9a-f]{40}$ ]]; then
  echo '--sha debe ser un SHA completo de 40 caracteres' >&2
  exit 2
fi
for file in "$operator_key_file" "$google_sa" "$env_file"; do
  if [[ -n $file && ! -s $file ]]; then
    echo "No existe o está vacío: $file" >&2
    exit 2
  fi
done
if [[ -n $google_sa && $no_google_sa == true ]]; then
  echo '--google-sa y --no-google-sa son incompatibles' >&2
  exit 2
fi

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "${original_args[@]}"
fi
# Relative file arguments must survive `sudo` (same cwd) but not any later `cd`.
for var in operator_key_file google_sa env_file; do
  [[ -z ${!var} || ${!var} == /* ]] || printf -v "$var" '%s/%s' "$PWD" "${!var}"
done

step_wanted() {
  local step=$1 item
  for item in "${skip_steps[@]:-}"; do [[ $item == "$step" ]] && return 1; done
  ((${#only_steps[@]})) || return 0
  for item in "${only_steps[@]}"; do [[ $item == "$step" ]] && return 0; done
  return 1
}

confirm() {
  [[ $assume_yes == true ]] && return 0
  [[ -t 0 ]] || return 1
  local reply
  read -r -p "$1 [s/N] " reply
  [[ $reply == s || $reply == S || $reply == y || $reply == Y ]]
}

as_deploy() { runuser -l deploy -c "$1"; }

# --- preflight (always) --------------------------------------------------------------

preflight() {
  grep -q '^VERSION_ID="24.04"$' /etc/os-release || die 'Hace falta Ubuntu 24.04'
  if [[ -z $repo_url ]]; then
    [[ -d $root/.git ]] || die 'Esto no es un clon de git: pasa --repo-url'
    repo_url=$(git -c safe.directory="$root" -C "$root" remote get-url origin 2>/dev/null) ||
      die 'El clon no tiene remoto origin: pasa --repo-url'
  fi
  repo_url=$(normalize_repo_url "$repo_url") ||
    die "La URL del repositorio no es https://<host>/<owner>/<repo>: $repo_url"
  slug=$(repo_slug "$repo_url")
  if [[ -z $image_owner ]]; then
    image_owner=$(printf '%s' "${slug%%/*}" | tr '[:upper:]' '[:lower:]')
  fi
  if [[ -z $public_host && $restore_target != true ]]; then
    public_host=$(env_get "$srv/.env" PUBLIC_HOST)
  fi
  if [[ -z $public_host && $restore_target != true ]] && step_wanted env; then
    die 'Falta --public-host (se guarda en .env la primera vez)'
  fi
  if [[ -z $sha ]]; then
    sha=$(git -c safe.directory="$root" -C "$root" rev-parse HEAD 2>/dev/null || true)
  fi
}

# --- operator key --------------------------------------------------------------------

# Writes the operator's public key (one line) to $1.
resolve_operator_key() {
  local out=$1 source_file line count=0
  # Only the key itself: any options before it (command=..., from=...) and the
  # trailing comment are dropped. `ssh-deploy.sh` in an option does not match.
  local key_re='ssh-(ed25519|rsa)[[:space:]]+[A-Za-z0-9+/=]+'
  if [[ -n $operator_key_file ]]; then
    source_file=$operator_key_file
  else
    local invoker=${SUDO_USER:-root} home
    home=$(getent passwd "$invoker" | cut -d: -f6)
    source_file=$home/.ssh/authorized_keys
    [[ -s $source_file ]] ||
      die "No hay clave del operador: $source_file no existe. Pasa --operator-key <fichero .pub>"
  fi
  while IFS= read -r line; do
    [[ $line =~ $key_re ]] || continue
    count=$((count + 1))
    printf '%s\n' "${BASH_REMATCH[0]}" >"$out"
  done <"$source_file"
  ((count == 1)) ||
    die "Se esperaba exactamente una clave pública en $source_file (hay $count). Pasa --operator-key <fichero .pub>"
  ssh-keygen -l -f "$out" >/dev/null || die 'La clave del operador no es válida'
}

# --- CI key ----------------------------------------------------------------------------

ensure_ci_key() {
  install -d -m 0755 "$state_dir"
  if [[ $rotate_ci_key == true || ! -s $ci_public ]]; then
    local work
    work=$(mktemp -d)
    ssh-keygen -q -t ed25519 -N '' -C autobot-ci -f "$work/key"
    install -m 0600 -o root -g root "$work/key" "$ci_private"
    install -m 0644 "$work/key.pub" "$ci_public"
    # The private key is only ever readable by root, and only until it is handed to
    # GitHub; best effort to wipe the temp copy.
    shred -u "$work/key" 2>/dev/null || rm -f "$work/key"
    rm -rf "$work"
    rotate_ci_key=false
    say 'Clave de CI generada (la privada queda en '"$ci_private"')'
  fi
}

ci_key_installed() {
  [[ -s $ci_public && -f /home/deploy/.ssh/authorized_keys ]] || return 1
  local blob
  blob=$(awk '{print $2}' "$ci_public")
  grep -qF "restrict,command=\"$srv/deploy/scripts/ssh-deploy.sh\" ssh-ed25519 $blob" \
    /home/deploy/.ssh/authorized_keys
}

# --- step: base ------------------------------------------------------------------------

check_base() {
  [[ -f $base_marker && -d $srv/.git ]] || return 1
  systemctl is-active --quiet docker || return 1
  systemctl is-enabled --quiet autobot-containers.timer || return 1
  systemctl is-enabled --quiet autobot-prune.timer || return 1
  systemctl is-enabled --quiet autobot-backup.timer || return 1
  ci_key_installed
}

do_base() {
  ensure_ci_key
  local work
  work=$(mktemp -d)
  resolve_operator_key "$work/operator.pub"
  cp "$ci_public" "$work/ci.pub"
  # Prefer the checkout the VM will actually run (an earlier run left it there).
  local script=$root/deploy/scripts/bootstrap-server.sh
  [[ -x $srv/deploy/scripts/bootstrap-server.sh ]] && script=$srv/deploy/scripts/bootstrap-server.sh
  REPO_URL=$repo_url bash "$script" --base "$work/operator.pub" "$work/ci.pub"
  rm -rf "$work"
}

check_ci_key() { [[ -s $ci_public && $rotate_ci_key != true ]]; }

do_ci_key() {
  ensure_ci_key
  # On an already installed machine (a rotation), put the new key into deploy's
  # authorized_keys right away; on a fresh one the base step does it.
  if [[ -f $base_marker ]]; then
    do_base
  fi
}

# --- step: env -------------------------------------------------------------------------

# Optional externals the operator may hand over (names only; values never printed).
env_keys=(DEMO_TELEGRAM_TOKEN DEMO_TELEGRAM_USERS DEMO_TELEGRAM_BOT_USERNAME NOTIFY_BOT_TOKEN
  OPS_TELEGRAM_CHAT_ID OWNER_SUPPORT_EMAIL PLATFORM_PRIVACY_URL SENTRY_DSN HEALTHCHECKS_PING_URL DEMO_SALON_CALENDAR_ID
  DEMO_WHATSAPP_PHONE_NUMBER_ID DEMO_WHATSAPP_WABA_ID DEMO_WHATSAPP_DISPLAY_PHONE
  DEMO_WHATSAPP_APP_SECRET DEMO_WHATSAPP_ACCESS_TOKEN DEMO_WHATSAPP_VERIFY_TOKEN DEMO_WHATSAPP_USERS)
backup_keys=(RESTIC_REPOSITORY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY HEALTHCHECKS_BACKUP_PING_URL)

in_list() {
  local needle=$1 item
  shift
  for item in "$@"; do [[ $item == "$needle" ]] && return 0; done
  return 1
}

check_env() {
  [[ -f $srv/.env && -f $srv/var/google_sa.json ]] || return 1
  local key
  for key in PUBLIC_HOST AUTOBOT_IMAGE AUTOBOT_PANEL_IMAGE FP_OWNER_PASSWORD SECRETS_ENCRYPTION_KEY \
    DB_APP_URL DEPLOY_UID; do
    [[ -n $(env_get "$srv/.env" "$key") ]] || return 1
  done
  [[ -z $public_host || $(env_get "$srv/.env" PUBLIC_HOST) == "$public_host" ]]
}

merge_env_file() {
  local line key value backup_env=$srv/var/backup.env backup_touched=false
  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line || $line == \#* ]] && continue
    [[ $line == *=* ]] || die "Línea inválida en $env_file (se esperaba CLAVE=valor)"
    key=${line%%=*}
    value=${line#*=}
    [[ -n $value ]] || continue
    if in_list "$key" "${env_keys[@]}"; then
      env_set "$srv/.env" "$key" "$value"
    elif in_list "$key" "${backup_keys[@]}"; then
      if [[ ! -f $backup_env ]]; then
        install -m 0600 -o deploy -g deploy /dev/null "$backup_env"
        printf 'RESTIC_PASSWORD_FILE=%s/var/restic-password\n' "$srv" >"$backup_env"
      fi
      env_set "$backup_env" "$key" "$value"
      backup_touched=true
    else
      die "Clave no admitida en $env_file: $key"
    fi
  done <"$env_file"
  chown deploy:deploy "$srv/.env"
  chmod 0600 "$srv/.env"
  if [[ $backup_touched == true ]]; then
    chown deploy:deploy "$backup_env"
    chmod 0600 "$backup_env"
  fi
}

do_env() {
  [[ -d $srv/.git ]] || die "Falta $srv: ejecuta antes el paso base"
  [[ -f $srv/.env ]] || install -m 0600 -o deploy -g deploy /dev/null "$srv/.env"
  chmod 0600 "$srv/.env"
  chown deploy:deploy "$srv/.env"
  local host=${public_host:?}
  # Explicit values replace; defaults only fill what is missing.
  env_set "$srv/.env" PUBLIC_HOST "$host"
  env_set "$srv/.env" DJANGO_ALLOWED_HOSTS "$host,localhost,127.0.0.1"
  if [[ $image_owner_given == true || -z $(env_get "$srv/.env" AUTOBOT_IMAGE) ]]; then
    env_set "$srv/.env" AUTOBOT_IMAGE "ghcr.io/$image_owner/autobot"
    env_set "$srv/.env" AUTOBOT_PANEL_IMAGE "ghcr.io/$image_owner/autobot-panel"
  fi
  chown deploy:deploy "$srv/.env"
  [[ -z $env_file ]] || merge_env_file

  install -d -m 0750 -o deploy -g deploy "$srv/var"
  if [[ -n $google_sa ]]; then
    install -m 0600 -o deploy -g deploy "$google_sa" "$srv/var/google_sa.json"
  elif [[ ! -f $srv/var/google_sa.json ]]; then
    [[ $no_google_sa == true ]] ||
      die 'Falta la cuenta de servicio de Google: pasa --google-sa <fichero.json> (o --no-google-sa si aún no la tienes)'
    printf '{}\n' | install -m 0600 -o deploy -g deploy /dev/stdin "$srv/var/google_sa.json"
    warn 'var/google_sa.json es un marcador vacío: Calendar no funcionará hasta subir el real'
  fi
  # Generates the internal secrets that are missing (never an external one).
  as_deploy "$srv/deploy/scripts/ensure-env.sh"
}

# --- step: deploy ----------------------------------------------------------------------

deployed_sha() { cat "$srv/var/.deployed-sha" 2>/dev/null || true; }

check_deploy() { [[ -n $sha && $(deployed_sha) == "$sha" ]]; }

do_deploy() {
  [[ -n $sha ]] || die 'No sé qué commit desplegar: pasa --sha'
  [[ -f $srv/.env ]] || die 'Falta .env: ejecuta antes el paso env'
  local image
  for image in autobot autobot-panel; do
    if ! docker manifest inspect "ghcr.io/$image_owner/$image:$sha" >/dev/null 2>&1; then
      die "La imagen ghcr.io/$image_owner/$image:$sha no está publicada (o el paquete es privado). Espera a que el CI de $sha termine en verde y que los paquetes de GHCR sean públicos; luego repite este paso."
    fi
  done
  say "Desplegando $sha (puede tardar unos minutos: descarga de imágenes y migraciones)"
  # Through the same forced command GitHub's CI uses: it checks that the commit is on
  # origin/main, takes the deploy lock *before* the checkout and runs deploy.sh.
  as_deploy "SSH_ORIGINAL_COMMAND='deploy/scripts/deploy.sh $sha' $srv/deploy/scripts/ssh-deploy.sh"
}

# --- step: health ----------------------------------------------------------------------

health_report() {
  local failed=0 web_port panel_port response host
  web_port=$(env_get "$srv/.env" AUTOBOT_WEB_HOST_PORT)
  panel_port=$(env_get "$srv/.env" AUTOBOT_PANEL_HOST_PORT)
  host=${public_host:-$(env_get "$srv/.env" PUBLIC_HOST)}
  if response=$(curl --silent --fail --max-time 5 "http://127.0.0.1:${web_port:-8000}/health/internal") &&
    python3 -c 'import json, sys
r = json.load(sys.stdin)
assert r["status"] == "ok" and r["tenants"]["unreadable"] == 0' <<<"$response" 2>/dev/null; then
    say '  [ok]    web: /health/internal responde y no hay negocios ilegibles'
  else
    say '  [FALLA] web: /health/internal no responde bien'
    failed=1
  fi
  if curl --silent --fail --max-time 5 "http://127.0.0.1:${panel_port:-8080}/healthz" >/dev/null; then
    say '  [ok]    panel: /healthz responde'
  else
    say '  [FALLA] panel: /healthz no responde'
    failed=1
  fi
  local service
  for service in worker-inbound worker-outbound; do
    if [[ -n $(docker ps -q --filter "label=com.docker.compose.project=autobot" \
      --filter "label=com.docker.compose.service=$service" --filter status=running) ]]; then
      say "  [ok]    $service en marcha"
    else
      say "  [FALLA] $service no está en marcha"
      failed=1
    fi
  done
  if [[ -n $host ]] && curl --silent --fail --max-time 8 --resolve "$host:443:127.0.0.1" "https://$host/health" >/dev/null; then
    say "  [ok]    HTTPS en $host responde (certificado válido)"
  else
    say "  [aviso] HTTPS en ${host:-?} no responde todavía: normal si el DNS aún no apunta aquí"
  fi
  local timer
  for timer in autobot-containers autobot-prune autobot-backup; do
    if systemctl is-enabled --quiet "$timer.timer"; then
      say "  [ok]    $timer.timer activado"
    else
      say "  [FALLA] $timer.timer no está activado"
      failed=1
    fi
  done
  return "$failed"
}

check_health() { health_report >/dev/null 2>&1; }

do_health() {
  say 'Comprobación de salud:'
  # shellcheck disable=SC2016 # literal backticks/$() in a message
  health_report || die 'La comprobación de salud ha fallado (ver arriba); revisa `deploy/scripts/compose.sh logs web`'
}

# --- step: harden-ssh ------------------------------------------------------------------

check_harden_ssh() {
  [[ -f $sshd_marker ]] &&
    [[ $(sshd -T | awk '/^permitrootlogin / {print $2}') == no ]] &&
    [[ $(sshd -T | awk '/^passwordauthentication / {print $2}') == no ]] &&
    [[ $(ufw status | head -n 1) == 'Status: active' ]]
}

do_harden_ssh() {
  [[ -f $base_marker ]] || die 'Falta el paso base antes de endurecer SSH'
  local port
  while read -r port; do
    [[ $port == 22 ]] || die "sshd escucha en el puerto $port: el endurecimiento solo contempla el 22 (abriría ufw sin él y te dejaría fuera)"
  done < <(sshd -T | awk '/^port / {print $2}')
  local work
  work=$(mktemp -d)
  resolve_operator_key "$work/operator.pub"
  local account
  for account in admin deploy; do
    if ! grep -qF "$(awk '{print $2}' "$work/operator.pub")" "/home/$account/.ssh/authorized_keys"; then
      rm -rf "$work"
      die "La clave del operador no está en /home/$account/.ssh/authorized_keys: no se endurece SSH"
    fi
  done
  rm -rf "$work"
  local ip
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  cat <<EOF

Endurecer SSH cierra el acceso de root, el de contraseña y el de cualquier usuario que
no sea admin o deploy (incluido el que estás usando ahora, si no es uno de ellos).
Antes de seguir, abre OTRA terminal y comprueba, con tu clave:
    ssh admin@${public_host:-${ip:-<ip>}}    y dentro:  sudo true
    ssh deploy@${public_host:-${ip:-<ip>}}   y dentro:  docker compose version
Si algo falla, no sigas: aquí tienes la consola del proveedor como salida de emergencia.
EOF
  if ! confirm 'Ya he comprobado ambas sesiones. ¿Endurecer SSH ahora?'; then
    warn 'SSH sin endurecer (sin confirmación). Repite con: sudo deploy/scripts/install-vm.sh --only harden-ssh'
    return 0
  fi
  bash "$srv/deploy/scripts/bootstrap-server.sh" --harden-ssh
}

# --- step: marker ----------------------------------------------------------------------

check_marker() { [[ -f $bootstrap_marker && -f $base_marker && -f $sshd_marker ]]; }

do_marker() {
  [[ -f $base_marker ]] || die 'Falta el paso base: no se escribe el marcador'
  if [[ ! -f $sshd_marker ]]; then
    warn 'SSH sin endurecer: no se escribe el marcador de bootstrap (restore.sh lo exigirá)'
    return 0
  fi
  install -d -m 0755 "$state_dir"
  {
    printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'installer_commit=%s\n' "$(git -c safe.directory="$root" -C "$root" rev-parse HEAD 2>/dev/null || echo unknown)"
  } >"$bootstrap_marker"
  say "Marcador escrito: $bootstrap_marker"
}

# --- step: github (optional) -----------------------------------------------------------

gh_ready() { command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; }

check_github() { return 1; }

do_github() {
  if [[ ! -s $ci_private ]]; then
    say 'No queda clave privada de CI en esta VM (ya entregada, o borrada): nada que subir.'
    return 0
  fi
  if ! gh_ready; then
    say 'gh no está instalado o autenticado en la VM: los secretos de GitHub quedan como paso manual (ver el resumen).'
    return 0
  fi
  confirm "¿Crear el entorno 'production' en $slug y subir DEPLOY_HOST, DEPLOY_SSH_KEY y DEPLOY_KNOWN_HOSTS con gh?" || {
    say 'Omitido: los secretos de GitHub quedan como paso manual.'
    return 0
  }
  local host=${public_host:-$(env_get "$srv/.env" PUBLIC_HOST)}
  # Only create it when missing: a PUT on an existing environment can reset the
  # reviewers and branch policy the operator set by hand.
  gh api "repos/$slug/environments/production" >/dev/null 2>&1 ||
    gh api -X PUT "repos/$slug/environments/production" >/dev/null
  gh secret set DEPLOY_HOST --repo "$slug" --env production --body "$host"
  gh secret set DEPLOY_SSH_KEY --repo "$slug" --env production <"$ci_private"
  known_hosts_line "$host" | gh secret set DEPLOY_KNOWN_HOSTS --repo "$slug" --env production
  shred -u "$ci_private"
  say "Secretos subidos y clave privada de CI borrada de la VM. Falta restringir el entorno a main (ver el resumen)."
}

# The VM's own host key, read locally: no trust-on-first-use over the network.
known_hosts_line() {
  printf '%s %s\n' "$1" "$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
}

# --- summary ---------------------------------------------------------------------------

summary() {
  local host=${public_host:-$(env_get "$srv/.env" PUBLIC_HOST)}
  host=${host:-<PUBLIC_HOST>}
  local ip n=0
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  say ''
  say '=============================================================================='
  say 'PASOS MANUALES PENDIENTES'
  say '=============================================================================='
  pending() { n=$((n + 1)); say ''; say "$n. $1"; shift; local line; for line in "$@"; do say "   $line"; done; }

  if [[ -n $host && $host != '<PUBLIC_HOST>' ]]; then
    local resolved
    resolved=$(getent hosts "$host" | awk '{print $1}' | head -n 1 || true)
    if [[ -z $resolved ]]; then
      pending "DNS: crea el registro A de $host apuntando a ${ip:-la IP de esta VM}" \
        'Hasta entonces Caddy no puede obtener el certificado HTTPS ni los webhooks llegan.'
    elif ! hostname -I 2>/dev/null | tr ' ' '\n' | grep -qx "$resolved"; then
      pending "DNS: $host resuelve a $resolved, que no es ninguna IP de esta VM (${ip:-?})" \
        'Si la VM está tras NAT/IP flotante del proveedor, ignóralo; si no, corrige el registro A.'
    fi
  fi

  if [[ -s $ci_private ]]; then
    # shellcheck disable=SC2016 # literal backticks/$() in a message
    pending 'GitHub: sube la clave de CI al entorno `production` y bórrala de la VM. Desde tu portátil:' \
      "ssh admin@$host 'sudo cat $ci_private' | gh secret set DEPLOY_SSH_KEY --env production" \
      "ssh admin@$host 'sudo shred -u $ci_private'" \
      "gh secret set DEPLOY_HOST --env production --body '$host'" \
      "y DEPLOY_KNOWN_HOSTS con la clave de host de esta VM:" \
      "ssh admin@$host \"cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub\" | sed \"s/^/$host /\" | gh secret set DEPLOY_KNOWN_HOSTS --env production" \
      '(si aún no existe el entorno: gh api -X PUT repos/'"$slug"'/environments/production)'
  fi
  # shellcheck disable=SC2016 # literal backticks/$() in a message
  pending 'GitHub: restringe el entorno `production` (Settings > Environments > production):' \
    'despliegues solo desde la rama main y revisores obligatorios. Sin esto, cualquier rama' \
    'con acceso al workflow puede usar la clave de despliegue.'
  pending 'GHCR: comprueba que los paquetes autobot y autobot-panel son públicos y que su retención cubre 6 meses.' \
    '(restaurar un snapshot antiguo necesita la imagen de su SHA; ver restaurar.md)'

  if [[ ! -f $srv/var/backup.env || ! -s $srv/var/restic-password ]] || [[ -z $(env_get "$srv/var/backup.env" RESTIC_REPOSITORY) ]]; then
    pending 'Backups: restic aún no está configurado. Como deploy en la VM:' \
      'crea var/backup.env (ver deploy/env/backup.env.example) con RESTIC_REPOSITORY, claves S3 y HEALTHCHECKS_BACKUP_PING_URL,' \
      'y var/restic-password (0600; guárdala también en tu gestor de contraseñas: sin ella los backups no se abren).' \
      'Después, A MANO (nunca automático): restic init, deploy/scripts/backup.sh una vez, y' \
      'sudo systemctl start autobot-backup.timer (como admin).'
  elif [[ ! -f $srv/var/.restic-repo-id ]]; then
    pending 'Backups: var/backup.env existe pero restic no se ha inicializado/probado. A mano, como deploy:' \
      'restic init (con ese entorno), luego deploy/scripts/backup.sh y, como admin, sudo systemctl start autobot-backup.timer.'
  elif ! systemctl is-active --quiet autobot-backup.timer; then
    pending 'Backups: el repositorio ya está inicializado; arranca el timer: sudo systemctl start autobot-backup.timer'
  fi

  local missing=()
  local key
  for key in HEALTHCHECKS_PING_URL SENTRY_DSN OPS_TELEGRAM_CHAT_ID NOTIFY_BOT_TOKEN DEMO_TELEGRAM_TOKEN; do
    [[ -n $(env_get "$srv/.env" "$key") ]] || missing+=("$key")
  done
  if ((${#missing[@]})); then
    # shellcheck disable=SC2016 # literal backticks/$() in a message
    pending "Credenciales externas sin rellenar en $srv/.env: ${missing[*]}" \
      'Healthchecks.io (HEALTHCHECKS_PING_URL y el de backup), Sentry, el chat de avisos y los tokens de Telegram.' \
      'Edítalo como deploy y relanza el último despliegue: deploy/scripts/deploy.sh $(cat var/.deployed-sha)' \
      '(o `docker compose` vía deploy/scripts/compose.sh up -d --no-deps web worker-inbound worker-outbound).'
  fi
  if [[ -f $srv/var/google_sa.json && $(tr -d '[:space:]' <"$srv/var/google_sa.json") == '{}' ]]; then
    pending 'Google: var/google_sa.json es un marcador vacío. Sustitúyelo por la cuenta de servicio real (0600, dueño deploy)' \
      'y comparte cada calendario con su correo; luego recrea web y worker-inbound.'
  fi
  if [[ -f $srv/var/.deployed-sha ]]; then
    pending 'Panel: crea el usuario del panel (interactivo; contraseña y TOTP):' \
      "ssh -t deploy@$host deploy/scripts/manage.sh panel_user create panel" \
      'y registra los webhooks de Telegram: manage.sh telegram_set_webhook demo / notify.'
  fi
  if [[ ! -f $sshd_marker ]]; then
    pending 'SSH: aún sin endurecer (root y contraseña abiertos, ufw sin activar).' \
      'Abre una sesión como admin@ y deploy@ con tu clave y ejecuta: sudo deploy/scripts/install-vm.sh --only harden-ssh --only marker'
  fi
  if ((n == 0)); then say 'No queda ningún paso manual.'; fi
  say ''
}

# --- main ------------------------------------------------------------------------------

preflight

# Order matters; each step only runs when requested and when it is not already done.
run_steps=(ci-key base env deploy health harden-ssh marker github)
failed_check=false
for step in "${run_steps[@]}"; do
  step_wanted "$step" || continue
  fn=${step//-/_}
  if [[ $check_only == true ]]; then
    if [[ $step == github ]]; then
      say "[manual ] $step"
    elif "check_$fn"; then
      say "[hecho  ] $step"
    else
      say "[pendiente] $step"
      failed_check=true
    fi
    continue
  fi
  say "== $step =="
  if [[ $step != github ]] && "check_$fn"; then
    say 'Ya hecho.'
    continue
  fi
  "do_$fn"
done

summary
if [[ $check_only == true && $failed_check == true ]]; then
  exit 1
fi
