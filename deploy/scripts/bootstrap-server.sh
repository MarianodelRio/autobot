#!/usr/bin/env bash
# Host-level setup of a new Ubuntu 24.04 VPS, as root or as a user with sudo. Normally
# run by `install-vm.sh` (ADR-017), inside the VM, which passes it the keys; it can
# also be run by hand. Safe to re-run. Two phases, run as two separate invocations:
#
#   REPO_URL=<https-url> bootstrap-server.sh --base <operator.pub> <ci.pub>
#   bootstrap-server.sh --harden-ssh
#
# --base never touches sshd: it is safe to repeat from the same session that is
# already in, and it is what install-vm.sh re-runs to check idempotency. It
# creates two accounts, both reachable only with the *same* operator keypair:
# `admin` (full sudo, for this script itself and any other host-level
# maintenance) and `deploy` (no sudo, in the `docker` group, holds the checkout
# and runs the containers; also accepts the CI key, restricted to deploy.sh).
# Giving `deploy` no sudo is not a real security boundary -- the `docker` group
# already lets it become root at will -- it only avoids accidents.
#
# --harden-ssh closes root/password SSH and restricts logins to deploy/admin; run
# it only after verifying, from a *separate* session, that both accounts accept
# the operator key (servidor.md). A mistake here can lock everyone out, so it is
# deliberately a second, explicit step, never folded into --base.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi
if ! grep -q '^VERSION_ID="24.04"$' /etc/os-release; then
  echo 'Ubuntu 24.04 is required' >&2
  exit 1
fi

phase=${1:-}
base_marker=/var/lib/autobot/bootstrap-base-complete
sshd_marker=/var/lib/autobot/bootstrap-sshd-complete

# Written by --base, compared by its idempotency check (a function so both use one text).
# Docker's own repository is an allowed origin, so docker-ce gets its security fixes too;
# a new daemon restarts the containers (restart: unless-stopped brings them back in seconds).
# Reboots, when a kernel update needs one, happen in a night window (server time, UTC on
# the VPS) away from the hourly backup at :00 and the demo traffic.
unattended_conf=/etc/apt/apt.conf.d/51autobot-unattended-upgrades
unattended_conf_text() {
  cat <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
Unattended-Upgrade::Allowed-Origins {
        "Docker:${distro_codename}";
};
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
CONF
}
firewall_bin=/usr/local/sbin/autobot-docker-firewall

case $phase in
--base)
  shift
  if [[ $# -ne 2 || ! -s $1 || ! -s $2 ]]; then
    echo 'Usage: REPO_URL=<https-url> bootstrap-server.sh --base <operator.pub> <ci.pub>' >&2
    exit 2
  fi
  : "${REPO_URL:?Set REPO_URL, e.g. https://github.com/<owner>/<repo>.git}"
  operator_key=$(cat "$1")
  ci_key=$(cat "$2")
  if [[ $(wc -l <"$1") -ne 1 || $(wc -l <"$2") -ne 1 ]] ||
    [[ ! $operator_key =~ ^ssh-(ed25519|rsa)[[:space:]][A-Za-z0-9+/=]+([[:space:]][^[:cntrl:]]*)?$ ]] ||
    [[ ! $ci_key =~ ^ssh-(ed25519|rsa)[[:space:]][A-Za-z0-9+/=]+([[:space:]][^[:cntrl:]]*)?$ ]] ||
    ! ssh-keygen -l -f "$1" >/dev/null || ! ssh-keygen -l -f "$2" >/dev/null; then
    echo 'Both files must contain an SSH public key' >&2
    exit 2
  fi
  fingerprint=$(cat "$1" "$2" "$0" <<<"$REPO_URL" | sha256sum | cut -d' ' -f1)
  ci_line="restrict,command=\"/srv/autobot/deploy/scripts/ssh-deploy.sh\" $ci_key"

  if [[ -f $base_marker && $(cat "$base_marker") == "$fingerprint" ]] &&
    systemctl is-active --quiet docker &&
    systemctl is-active --quiet unattended-upgrades &&
    systemctl is-enabled --quiet autobot-backup.timer &&
    systemctl is-enabled --quiet autobot-containers.timer &&
    systemctl is-enabled --quiet autobot-prune.timer &&
    systemctl is-enabled --quiet autobot-docker-firewall.service &&
    cmp -s <(unattended_conf_text) "$unattended_conf" &&
    cmp -s /srv/autobot/deploy/scripts/docker-user-firewall.sh "$firewall_bin" &&
    cmp -s /srv/autobot/deploy/systemd/autobot-docker-firewall.service /etc/systemd/system/autobot-docker-firewall.service &&
    cmp -s /home/deploy/.ssh/authorized_keys <(printf '%s\n%s\n' "$operator_key" "$ci_line") &&
    cmp -s /home/admin/.ssh/authorized_keys <(printf '%s\n' "$operator_key") &&
    id -nG admin | tr ' ' '\n' | grep -qx sudo &&
    swapon --show=NAME --noheadings | grep -qx /swapfile &&
    cmp -s /srv/autobot/deploy/systemd/autobot-backup.timer /etc/systemd/system/autobot-backup.timer &&
    cmp -s /srv/autobot/deploy/systemd/autobot-backup.service /etc/systemd/system/autobot-backup.service &&
    cmp -s /srv/autobot/deploy/systemd/autobot-containers.timer /etc/systemd/system/autobot-containers.timer &&
    cmp -s /srv/autobot/deploy/systemd/autobot-containers.service /etc/systemd/system/autobot-containers.service &&
    cmp -s /srv/autobot/deploy/systemd/autobot-prune.timer /etc/systemd/system/autobot-prune.timer &&
    cmp -s /srv/autobot/deploy/systemd/autobot-prune.service /etc/systemd/system/autobot-prune.service &&
    [[ $(stat -c '%u:%g:%a' /srv/autobot/var/state/caddy-data) == "$(id -u deploy):$(id -g deploy):700" ]] &&
    [[ $(stat -c '%u:%g:%a' /srv/autobot/var/state/caddy-config) == "$(id -u deploy):$(id -g deploy):700" ]] &&
    [[ $(stat -c '%u:%g:%a' /srv/autobot/var/state/ops) == "$(id -u deploy):$(id -g deploy):700" ]]; then
    echo 'Base bootstrap already configured'
    exit 0
  fi

  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git ufw fail2ban unattended-upgrades restic
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    install -m 0755 -d /etc/apt/keyrings
    curl --fail --silent --show-error https://download.docker.com/linux/ubuntu/gpg \
      -o /etc/apt/keyrings/docker.asc
    chmod 0644 /etc/apt/keyrings/docker.asc
  fi
  if [[ ! -f /etc/apt/sources.list.d/docker.sources ]]; then
    # VERSION_CODENAME is provided by Ubuntu's os-release file.
    # shellcheck source=/dev/null
    source /etc/os-release
    cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $VERSION_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    apt-get update -qq
  fi
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker unattended-upgrades
  unattended_conf_text >"$unattended_conf"
  chmod 0644 "$unattended_conf"

  # A on a 2 vCPU/4 GB VPS: 2 GB of swap, as a cushion under real load (measured
  # properly later), never as a substitute for picking a bigger machine.
  if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
    if [[ ! -f /swapfile ]]; then
      fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
      chmod 600 /swapfile
      mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
  fi
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab

  if ! id deploy >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash deploy
  fi
  usermod -aG docker deploy
  if ! id admin >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash admin
  fi
  usermod -aG sudo admin
  # Key-only access everywhere (PasswordAuthentication is disabled by
  # --harden-ssh): there is no password to prompt for, so admin's sudo must not
  # block on one either.
  cat >/etc/sudoers.d/autobot-admin <<'EOF'
admin ALL=(ALL) NOPASSWD:ALL
EOF
  chmod 0440 /etc/sudoers.d/autobot-admin
  visudo -cf /etc/sudoers.d/autobot-admin

  install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
  deploy_keys=$(mktemp)
  admin_keys=$(mktemp)
  trap 'rm -f "$deploy_keys" "$admin_keys"' EXIT
  printf '%s\n%s\n' "$operator_key" "$ci_line" >"$deploy_keys"
  if ! cmp -s "$deploy_keys" /home/deploy/.ssh/authorized_keys; then
    install -m 0600 -o deploy -g deploy "$deploy_keys" /home/deploy/.ssh/authorized_keys
  fi
  install -d -m 0700 -o admin -g admin /home/admin/.ssh
  printf '%s\n' "$operator_key" >"$admin_keys"
  if ! cmp -s "$admin_keys" /home/admin/.ssh/authorized_keys; then
    install -m 0600 -o admin -g admin "$admin_keys" /home/admin/.ssh/authorized_keys
  fi

  # The repo is public: a plain HTTPS clone needs no deploy key at all, and
  # ssh-deploy.sh/deploy.sh still only ever check out a SHA that CI already built
  # from `main`.
  install -d -m 0750 -o deploy -g deploy /srv/autobot
  if [[ ! -d /srv/autobot/.git ]]; then
    runuser -u deploy -- git clone --quiet "$REPO_URL" /srv/autobot
  fi
  install -d -m 0750 -o deploy -g deploy /srv/autobot/var
  install -d -m 0700 -o deploy -g deploy /srv/autobot/var/state/caddy-data
  install -d -m 0700 -o deploy -g deploy /srv/autobot/var/state/caddy-config
  install -d -m 0700 -o deploy -g deploy /srv/autobot/var/state/ops

  install -m 0644 /srv/autobot/deploy/systemd/autobot-backup.service /etc/systemd/system/
  install -m 0644 /srv/autobot/deploy/systemd/autobot-backup.timer /etc/systemd/system/
  install -m 0644 /srv/autobot/deploy/systemd/autobot-containers.service /etc/systemd/system/
  install -m 0644 /srv/autobot/deploy/systemd/autobot-containers.timer /etc/systemd/system/
  install -m 0644 /srv/autobot/deploy/systemd/autobot-prune.service /etc/systemd/system/
  install -m 0644 /srv/autobot/deploy/systemd/autobot-prune.timer /etc/systemd/system/
  # Root runs this one, so it is a root-owned copy, never the checkout's own (deploy's).
  install -m 0755 -o root -g root /srv/autobot/deploy/scripts/docker-user-firewall.sh "$firewall_bin"
  install -m 0644 /srv/autobot/deploy/systemd/autobot-docker-firewall.service /etc/systemd/system/
  systemctl daemon-reload
  # Not started yet: install-vm.sh starts the backup timer only once
  # var/backup.env and the restic password are in place; enabling it now
  # just means it is ready without racing a backup against an unconfigured host.
  systemctl enable autobot-backup.timer
  # Read-only snapshot: safe to enable and start immediately, unlike the backup timer.
  systemctl enable --now autobot-containers.timer
  # only removes images no container references; safe to start right away too.
  systemctl enable --now autobot-prune.timer
  # Rejects, before UFW even sees them, connections to any published Docker port that is not
  # 80/443 (see docker-user-firewall.sh).
  systemctl enable --now autobot-docker-firewall.service
  install -d -m 0755 /var/lib/autobot
  printf '%s\n' "$fingerprint" >"$base_marker"
  echo 'Base bootstrap completed. Open a NEW session as both deploy@ and admin@ with'
  echo 'the operator key before running --harden-ssh (closing this one does not count).'
  ;;

--harden-ssh)
  ufw_rules_safe() {
    ufw show added | awk '/^ufw / && $0 !~ /^ufw allow (22|80|443)\/tcp$/ {bad=1} END {exit bad?1:0}'
  }
  ufw_rules_complete() {
    ufw show added | awk '
      /^ufw allow 22\/tcp$/ {ssh=1; next}
      /^ufw allow 80\/tcp$/ {http=1; next}
      /^ufw allow 443\/tcp$/ {https=1; next}
      /^ufw / {bad=1}
      END {exit (ssh && http && https && !bad)?0:1}'
  }
  if [[ -f $sshd_marker ]] &&
    systemctl is-active --quiet fail2ban &&
    systemctl is-active --quiet ssh &&
    [[ $(ufw status | head -n 1) == 'Status: active' ]] &&
    ufw_rules_complete &&
    grep -q '^DEFAULT_INPUT_POLICY="DROP"$' /etc/default/ufw &&
    [[ $(sshd -T | awk '/^permitrootlogin / {print $2}') == no ]] &&
    [[ $(sshd -T | awk '/^passwordauthentication / {print $2}') == no ]] &&
    [[ $(sshd -T | awk '/^maxauthtries / {print $2}') == 4 ]] &&
    [[ $(sshd -T | awk '/^logingracetime / {print $2}') == 30 ]]; then
    echo 'SSH hardening already configured'
    exit 0
  fi
  if [[ ! -f $base_marker ]]; then
    echo '--base has not completed on this host yet; run it first' >&2
    exit 1
  fi

  cat >/etc/ssh/sshd_config.d/00-00-autobot.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers deploy admin
# Key-only logins need a few tries at most (4, not 3: an operator whose agent holds several
# keys would otherwise get locked out by its own key list; `ssh -o IdentitiesOnly=yes -i`
# avoids that) and a short window to authenticate, which keeps unauthenticated connections
# from piling up.
MaxAuthTries 4
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
  sshd -t
  if [[ $(sshd -T | awk '/^permitrootlogin / {print $2}') != no ]] ||
    [[ $(sshd -T | awk '/^passwordauthentication / {print $2}') != no ]] ||
    [[ $(sshd -T | awk '/^kbdinteractiveauthentication / {print $2}') != no ]]; then
    echo 'Effective SSH policy is not hardened; refusing reload' >&2
    exit 1
  fi
  systemctl reload ssh
  cat >/etc/fail2ban/jail.d/autobot-sshd.local <<'EOF'
[sshd]
enabled = true
EOF
  systemctl enable --now fail2ban
  systemctl restart fail2ban
  if ! ufw_rules_safe; then
    echo 'Unexpected existing UFW allow rule; inspect and remove it first' >&2
    exit 1
  fi
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  install -d -m 0755 /var/lib/autobot
  touch "$sshd_marker"
  echo 'SSH hardening completed: root/password logins closed, only deploy/admin allowed'
  ;;

*)
  cat >&2 <<EOF
Usage:
  REPO_URL=<https-url> bootstrap-server.sh --base <operator.pub> <ci.pub>
  bootstrap-server.sh --harden-ssh
EOF
  exit 2
  ;;
esac
