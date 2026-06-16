#!/bin/bash
# Provision a fresh Ubuntu 24.04 EC2 instance for asterisk-sandbox.
# Run as the ubuntu user (passwordless sudo). Safe to re-run.

set -euo pipefail

ENV_FILE="$HOME/asterisk-sandbox/.env"

# Bootstrap: .env must exist before the repo is cloned on first run.
# Copy .env.example from the repo manually, or drop it at $HOME/.env first.
if [[ -f "$HOME/.env" && ! -f "$HOME/asterisk-sandbox/.env" ]]; then
    mkdir -p "$HOME/asterisk-sandbox"
    cp "$HOME/.env" "$HOME/asterisk-sandbox/.env"
fi

if [[ ! -f "$HOME/asterisk-sandbox/.env" ]]; then
    echo "error: no .env found. Copy .env.example, fill in values, place at $HOME/.env, then re-run."
    exit 1
fi

# shellcheck source=/dev/null
source "$HOME/asterisk-sandbox/.env"

: "${DOMAIN:?DOMAIN not set in .env}"
: "${EMAIL:?EMAIL not set in .env}"
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
if [[ ! -d "$REPO_DIR" ]]; then
    git clone "$REPO_URL" "$REPO_DIR"
else
    git -C "$REPO_DIR" pull --ff-only
fi
cd "$REPO_DIR"

echo "==> .env"
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo ""
    echo "STOP: fill in .env then re-run:"
    echo "  nano $REPO_DIR/.env"
    exit 1
fi

echo "==> asterisk config"
sudo bash scripts/link-configs.sh
sudo bash scripts/gen-configs.sh

echo "==> python deps"
uv sync

echo "==> TLS cert"
# nginx starts with Ubuntu default config (HTTP only) - enough for the ACME challenge
sudo systemctl start nginx
sudo certbot certonly --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"

echo "==> nginx site"
# gen-configs.sh already wrote the site config; just symlink and reload
sudo ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "==> fastapi service"
sudo cp scripts/fastapi.service /etc/systemd/system/asterisk-fastapi.service
sudo systemctl daemon-reload
sudo systemctl enable --now asterisk-fastapi

echo "==> asterisk"
sudo systemctl enable --now asterisk

echo ""
echo "done -- verify:"
echo "  sudo systemctl status asterisk asterisk-fastapi nginx"
echo "  curl https://$DOMAIN/health"
