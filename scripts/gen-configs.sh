#!/bin/bash
# Generate configs from *.template files, substituting from .env.
# Run after editing .env, then restart services.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "error: .env not found -- copy .env.example and fill in values" >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$REPO_ROOT/.env"
set +a

generate() {
    local vars="$1"
    local template="$2"
    local dest="$3"
    envsubst "$vars" < "$template" | sudo tee "$dest" > /dev/null
    echo "generated $dest"
}

generate '${AMI_SECRET}' \
    "$REPO_ROOT/asterisk/manager.conf.template" \
    /etc/asterisk/manager.conf

generate '${SIP_PASS_01},${SIP_PASS_02},${DOMAIN}' \
    "$REPO_ROOT/asterisk/pjsip.conf.template" \
    /etc/asterisk/pjsip.conf

if [[ -n "${DOMAIN:-}" ]]; then
    generate '${DOMAIN}' \
        "$REPO_ROOT/nginx/pbx.conf.template" \
        "/etc/nginx/sites-available/$DOMAIN"
    echo "nginx config written -- symlink and reload nginx to apply"
fi

echo "done -- restart with: sudo systemctl restart asterisk && sudo systemctl reload nginx"
