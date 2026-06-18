#!/bin/bash
# Obtain the Let's Encrypt cert for $DOMAIN. Requires DNS for $DOMAIN to resolve
# to this box and nginx serving HTTP (provision.sh sets that up). Idempotent:
# skips if a live cert already exists. Ongoing renewal is handled by certbot's
# own systemd timer, not this script. Pass --force to re-issue.
# Run as the target user (e.g. ubuntu).

set -euo pipefail

if [[ ! -f "$HOME/.env" ]]; then
    echo "error: no ~/.env found." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$HOME/.env"
: "${DOMAIN:?DOMAIN not set in .env}"
: "${EMAIL:?EMAIL not set in .env}"

# Renewal reload hook. We issue with `certonly`, so certbot's renewal timer fetches
# a fresh cert but does NOT touch or reload nginx -- without this, nginx keeps
# serving the old cert until it expires (~90 days out, silently). Deploy hooks run
# after every successful renewal regardless of how the cert was first issued, so
# installing it here also fixes a box whose cert was issued before the hook existed.
# Installed every run (idempotent), before the already-present short-circuit below.
sudo install -d /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh > /dev/null <<'HOOK'
#!/bin/sh
# Installed by certs.sh -- reload nginx so a renewed cert takes effect.
systemctl reload nginx
HOOK
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

force=""
[[ "${1:-}" == "--force" ]] && force="--force-renewal"

if [[ -d "/etc/letsencrypt/live/$DOMAIN" && -z "$force" ]]; then
    echo "cert for $DOMAIN already present -- skipping issuance (renewal hook ensured)"
    exit 0
fi

# nginx must be serving HTTP for the ACME http-01 challenge.
sudo systemctl is-active --quiet nginx || sudo systemctl start nginx

# shellcheck disable=SC2086
sudo certbot certonly --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" $force

echo "done -- cert obtained for $DOMAIN"
