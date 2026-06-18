#!/bin/bash
# One-time host provisioning for asterisk-sandbox: system packages, uv, the repo
# checkout, the .env, and base services on HTTP. After this, point DNS for
# $DOMAIN at this box, then run certs.sh and apply-repo.sh -- or just setup.sh,
# which orchestrates all three. Run as the target user (e.g. ubuntu); idempotent.

set -euo pipefail

if [[ ! -f "$HOME/.env" ]]; then
    echo "error: no ~/.env found. Copy .env.example, fill in values, place at $HOME/.env, then re-run." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$HOME/.env"
: "${REPO_URL:?REPO_URL not set in .env}"

REPO_DIR="$HOME/asterisk-sandbox"

echo "==> system packages"
sudo apt-get update -q
sudo apt-get upgrade -y -q
sudo apt-get install -y -q asterisk nginx certbot python3-certbot-nginx git curl gettext-base

echo "==> uv"
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env"
fi

echo "==> repo"
if [[ ! -d "$REPO_DIR/.git" ]]; then
    git clone "$REPO_URL" "$REPO_DIR"
else
    git -C "$REPO_DIR" pull --ff-only
fi

echo "==> .env"
if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$HOME/.env" "$REPO_DIR/.env"
fi

echo "==> base services (HTTP)"
sudo systemctl enable --now asterisk nginx

echo ""
echo "done -- provisioned. next:"
echo "  point DNS for ${DOMAIN:-<domain>} at this box, then:"
echo "  bash $REPO_DIR/scripts/certs.sh && bash $REPO_DIR/scripts/apply-repo.sh"
