#!/usr/bin/env bash
# Execute manually as root on a new Ubuntu 24.04 VPS. Safe to re-run.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo 'Run as root on the new VPS' >&2
  exit 1
fi
if ! grep -q '^VERSION_ID="24.04"$' /etc/os-release; then
  echo 'Ubuntu 24.04 is required' >&2
  exit 1
fi
if [[ $# -ne 4 || ! -s $1 || ! -s $2 || ! -s $3 || ! -s $4 ]]; then
  echo 'Usage: bootstrap-server.sh <operator.pub> <ci.pub> <github-read-key> <github-known-hosts>' >&2
  exit 2
fi
operator_key=$(cat "$1")
ci_key=$(cat "$2")
if [[ $(wc -l <"$1") -ne 1 || $(wc -l <"$2") -ne 1 ]] || \
   [[ ! $operator_key =~ ^ssh-(ed25519|rsa)[[:space:]][A-Za-z0-9+/=]+([[:space:]][^[:cntrl:]]*)?$ ]] || \
   [[ ! $ci_key =~ ^ssh-(ed25519|rsa)[[:space:]][A-Za-z0-9+/=]+([[:space:]][^[:cntrl:]]*)?$ ]] || \
   ! ssh-keygen -l -f "$1" >/dev/null || ! ssh-keygen -l -f "$2" >/dev/null; then
  echo 'Both files must contain an SSH public key' >&2
  exit 2
fi
fingerprint=$(cat "$1" "$2" "$3" "$4" "$0" | sha256sum | cut -d' ' -f1)
marker=/var/lib/autobot/bootstrap-complete
operator_line="$operator_key"
ci_line="restrict,command=\"/srv/autobot/deploy/ssh-deploy.sh\" $ci_key"
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
if [[ -f $marker && $(cat "$marker") == "$fingerprint" ]] && \
   systemctl is-active --quiet docker && \
   systemctl is-active --quiet fail2ban && \
   systemctl is-active --quiet ssh && \
   systemctl is-enabled --quiet autobot-backup.timer && \
   [[ $(ufw status | head -n 1) == 'Status: active' ]] && \
   ufw_rules_complete && \
   grep -q '^DEFAULT_INPUT_POLICY="DROP"$' /etc/default/ufw && \
   cmp -s /home/deploy/.ssh/authorized_keys \
     <(printf '%s\n%s\n' "$operator_line" "$ci_line") && \
   cmp -s /srv/autobot/deploy/autobot-backup.timer /etc/systemd/system/autobot-backup.timer && \
   cmp -s /srv/autobot/deploy/autobot-backup.service /etc/systemd/system/autobot-backup.service && \
   [[ $(stat -c '%u:%g:%a' /srv/autobot/state/caddy-data) == "$(id -u deploy):$(id -g deploy):700" ]] && \
   [[ $(stat -c '%u:%g:%a' /srv/autobot/state/caddy-config) == "$(id -u deploy):$(id -g deploy):700" ]] && \
   [[ $(sshd -T | awk '/^permitrootlogin / {print $2}') == no ]] && \
   [[ $(sshd -T | awk '/^passwordauthentication / {print $2}') == no ]]; then
  echo 'Bootstrap already configured'
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
systemctl enable --now docker unattended-upgrades fail2ban

if ! id deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash deploy
fi
usermod -aG docker deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
install -m 0600 -o deploy -g deploy "$3" /home/deploy/.ssh/github_readonly
install -m 0600 -o deploy -g deploy "$4" /home/deploy/.ssh/known_hosts
keys=$(mktemp)
trap 'rm -f "$keys"' EXIT
printf '%s\n%s\n' "$operator_line" "$ci_line" >"$keys"
if ! cmp -s "$keys" /home/deploy/.ssh/authorized_keys; then
  install -m 0600 -o deploy -g deploy "$keys" /home/deploy/.ssh/authorized_keys
fi

install -d -m 0750 -o deploy -g deploy /srv/autobot
if [[ ! -d /srv/autobot/.git ]]; then
  runuser -u deploy -- env GIT_SSH_COMMAND='ssh -i /home/deploy/.ssh/github_readonly -o IdentitiesOnly=yes -o UserKnownHostsFile=/home/deploy/.ssh/known_hosts -o StrictHostKeyChecking=yes' \
    git clone --quiet git@github.com:MarianodelRio/autobot.git /srv/autobot
fi
runuser -u deploy -- git -C /srv/autobot config core.sshCommand \
  'ssh -i /home/deploy/.ssh/github_readonly -o IdentitiesOnly=yes -o UserKnownHostsFile=/home/deploy/.ssh/known_hosts -o StrictHostKeyChecking=yes'
install -d -m 0700 -o deploy -g deploy /srv/autobot/state/caddy-data
install -d -m 0700 -o deploy -g deploy /srv/autobot/state/caddy-config

cat >/etc/ssh/sshd_config.d/00-00-autobot.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers deploy
EOF
sshd -t
if [[ $(sshd -T | awk '/^permitrootlogin / {print $2}') != no ]] || \
   [[ $(sshd -T | awk '/^passwordauthentication / {print $2}') != no ]] || \
   [[ $(sshd -T | awk '/^kbdinteractiveauthentication / {print $2}') != no ]]; then
  echo 'Effective SSH policy is not hardened; refusing reload' >&2
  exit 1
fi
systemctl reload ssh
cat >/etc/fail2ban/jail.d/autobot-sshd.local <<'EOF'
[sshd]
enabled = true
EOF
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

install -m 0644 /srv/autobot/deploy/autobot-backup.service /etc/systemd/system/
install -m 0644 /srv/autobot/deploy/autobot-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable autobot-backup.timer
install -d -m 0755 /var/lib/autobot
printf '%s\n' "$fingerprint" >"$marker"
echo 'Bootstrap completed; configure secrets and GHCR read access before deploy'
