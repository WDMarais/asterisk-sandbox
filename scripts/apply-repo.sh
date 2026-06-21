#!/bin/bash
# Apply this repo's current state to an already-provisioned box: re-link and
# re-render configs, (re)install the systemd service and logrotate, sync deps,
# then reload services so a `git pull` takes effect in one step.
#
# The lightweight counterpart to setup.sh -- it skips the one-time provisioning
# (apt packages, uv install, repo clone, TLS cert issuance) and assumes those
# are already in place. Run as the repo user (e.g. ubuntu); uses sudo for the
# privileged steps.
#
#   git pull --ff-only && bash scripts/apply-repo.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f ".env" ]]; then
    echo "error: .env not found in $REPO_ROOT -- box not provisioned; run setup.sh first" >&2
    exit 1
fi
set -a
# shellcheck source=/dev/null
source .env
set +a

# uv lives in ~/.local/bin, which a non-interactive shell may not have on PATH.
# shellcheck source=/dev/null
[[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env"

echo "==> asterisk + nginx config"
sudo bash scripts/link-configs.sh
bash scripts/render-configs.sh

echo "==> log rotation"
sudo cp asterisk/logrotate.conf /etc/logrotate.d/asterisk
echo '0 * * * * root /usr/sbin/logrotate /etc/logrotate.d/asterisk' \
    | sudo tee /etc/cron.d/asterisk-logrotate-hourly > /dev/null

echo "==> fail2ban (SIP scanner bans)"
if command -v fail2ban-client > /dev/null; then
    sudo cp fail2ban/filter.d/asterisk-pjsip.conf /etc/fail2ban/filter.d/asterisk-pjsip.conf
    sudo cp fail2ban/jail.d/asterisk-pjsip.local /etc/fail2ban/jail.d/asterisk-pjsip.local
    sudo systemctl restart fail2ban
else
    echo "fail2ban not installed -- skipping (sudo apt-get install -y fail2ban, then re-run)"
fi

echo "==> fastapi service"
sudo cp scripts/fastapi.service /etc/systemd/system/asterisk-fastapi.service
sudo systemctl daemon-reload
sudo systemctl enable asterisk-fastapi

echo "==> python deps"
uv sync

echo "==> reload services"
# Enable our site and drop the Ubuntu default (idempotent). The TLS site
# references /etc/letsencrypt/live/$DOMAIN, so the cert must already exist --
# setup.sh obtains it before the first call here.
sudo ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo asterisk -rx "core reload" > /dev/null
sudo systemctl restart asterisk-fastapi

echo ""
echo "done -- verify:"
echo "  systemctl is-active asterisk asterisk-fastapi nginx"
echo "  curl -s https://${DOMAIN}/health"
