#!/bin/bash
# Provision + cert + apply, end to end, for asterisk-sandbox on Ubuntu 24.04.
# Run as the target user (e.g. ubuntu) with passwordless sudo. Safe to re-run.
#
# Orchestrates the three lifecycle scripts:
#   provision.sh   one-time host prep (packages, uv, repo, base services)
#   certs.sh       Let's Encrypt cert for $DOMAIN (needs DNS pointing here)
#   apply-repo.sh  link/render configs, install service + logrotate, reload
#
# On a fresh domain whose DNS doesn't resolve to this box yet, it provisions,
# tells you to point DNS, and stops cleanly -- re-run setup.sh (or run
# certs.sh && apply-repo.sh) once DNS is live.

set -euo pipefail

if [[ ! -f "$HOME/.env" ]]; then
    echo "error: no ~/.env found. Copy .env.example, fill in values, place at $HOME/.env, then re-run." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$HOME/.env"
: "${DOMAIN:?DOMAIN not set in .env}"
: "${EMAIL:?EMAIL not set in .env}"
: "${REPO_URL:?REPO_URL not set in .env}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

bash "$SCRIPT_DIR/provision.sh"

# Cert issuance needs DNS for $DOMAIN to resolve to this box's public IP.
# If it doesn't yet, stop cleanly after provisioning and guide the operator.
public_ip="$(curl -fsS https://checkip.amazonaws.com 2>/dev/null || true)"
resolved_ip="$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}')"
if [[ -z "$resolved_ip" || ( -n "$public_ip" && "$resolved_ip" != "$public_ip" ) ]]; then
    echo ""
    echo "DNS for $DOMAIN does not resolve to this box yet:"
    echo "  this box:    ${public_ip:-<unknown>}"
    echo "  $DOMAIN -> ${resolved_ip:-<unresolved>}"
    echo "point DNS at this box, then finish with:"
    echo "  bash $SCRIPT_DIR/certs.sh && bash $SCRIPT_DIR/apply-repo.sh"
    exit 0
fi

bash "$SCRIPT_DIR/certs.sh"
bash "$SCRIPT_DIR/apply-repo.sh"

echo ""
echo "done -- verify:"
echo "  sudo systemctl status asterisk asterisk-fastapi nginx"
echo "  curl https://$DOMAIN/health"
