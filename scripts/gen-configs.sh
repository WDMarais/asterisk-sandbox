#!/bin/bash
# Generate /etc/asterisk configs from *.template files, substituting from .env.
# Run after editing .env, then restart Asterisk.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "error: .env not found — copy .env.example and fill in values" >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$REPO_ROOT/.env"
set +a

generate() {
    local template="$1"
    local dest="$2"
    envsubst < "$template" | sudo tee "$dest" > /dev/null
    echo "generated $dest"
}

generate "$REPO_ROOT/asterisk/manager.conf.template" /etc/asterisk/manager.conf

echo "done — restart with: sudo systemctl restart asterisk"
