#!/usr/bin/env bash
# Run as root by autobot-docker-firewall.service (installed by bootstrap-server.sh as
# /usr/local/sbin/autobot-docker-firewall, a root-owned copy: the checkout belongs to
# `deploy`, which must not be able to change what root runs).
#
# UFW does not filter what Docker publishes: a `ports:` entry without 127.0.0.1 is reachable
# from the internet whatever `ufw status` says, because Docker's DNAT rules run before UFW's
# INPUT chain. DOCKER-USER is the chain Docker evaluates first for forwarded traffic and
# never overwrites, so this is the one place to enforce the allowlist of ADR-020:
# connections that were DNAT'd to a container (that is, to a published port) pass only if the
# port the client asked for is 80 or 443 (Caddy). Everything else is dropped.
#
# Not affected: SSH and anything else on the host itself (INPUT chain), connections the
# containers open outwards (their replies are not DNAT'd), traffic between containers, and
# the host's own access to 127.0.0.1:8000 / :8080 (it never goes through FORWARD).
# Idempotent: the chain is rebuilt from scratch on every run.
set -euo pipefail

if ! iptables -w -n -L DOCKER-USER >/dev/null 2>&1; then
  echo 'DOCKER-USER does not exist: is Docker running?' >&2
  exit 1
fi
iptables -w -F DOCKER-USER
iptables -w -A DOCKER-USER -p tcp -m conntrack --ctstate DNAT --ctorigdstport 80 -j RETURN
iptables -w -A DOCKER-USER -p tcp -m conntrack --ctstate DNAT --ctorigdstport 443 -j RETURN
iptables -w -A DOCKER-USER -m conntrack --ctstate DNAT -j DROP
# Docker's own default for the chain: everything else continues to its own rules.
iptables -w -A DOCKER-USER -j RETURN
