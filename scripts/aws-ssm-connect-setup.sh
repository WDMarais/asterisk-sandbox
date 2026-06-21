#!/bin/bash
# Local workstation setup for connecting to the VPS over SSM. Installs the
# session-manager-plugin and prints (or, with --write, appends) an SSH-over-SSM
# Host block to ~/.ssh/config, so `ssh $SSH_HOST_ALIAS`, scp, rsync and git all
# tunnel through SSM using your existing SSH key. SSM is only the transport;
# SSH still does user auth, so nothing about your key changes.
#
# Run on your workstation (WSL), not the VPS. Idempotent. Requires the aws CLI
# configured and the instance already SSM-reachable (run aws-ssm-setup.sh first).
#
# Config (env vars; defaults shown):
#   INSTANCE_ID=i-...   (required)
#   AWS_REGION=af-south-1   SSH_HOST_ALIAS=pbx   SSH_USER=ubuntu
# Flags:
#   --write   append the Host block to ~/.ssh/config (default: just print it)

set -euo pipefail

AWS_REGION="${AWS_REGION:-af-south-1}"
SSH_HOST_ALIAS="${SSH_HOST_ALIAS:-pbx}"
SSH_USER="${SSH_USER:-ubuntu}"
WRITE=0
[[ "${1:-}" == "--write" ]] && WRITE=1

: "${INSTANCE_ID:?set INSTANCE_ID=i-... (the instance from aws-ssm-setup.sh)}"
command -v aws >/dev/null || { echo "error: aws CLI not found -- install and 'aws configure' first" >&2; exit 1; }

# --- session-manager-plugin (Debian/Ubuntu deb) ---------------------------
echo "==> session-manager-plugin"
if command -v session-manager-plugin >/dev/null; then
    echo "already installed"
else
    tmp="$(mktemp -d)"
    curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" \
        -o "$tmp/smp.deb"
    sudo dpkg -i "$tmp/smp.deb"
    rm -rf "$tmp"
    echo "installed"
fi

# --- ssh config block ------------------------------------------------------
marker="asterisk-sandbox SSM access"
block="$(cat <<EOF

# >>> $marker >>>
Host $SSH_HOST_ALIAS
    HostName $INSTANCE_ID
    User $SSH_USER
    ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p' --region $AWS_REGION"
# <<< $marker <<<
EOF
)"

if [[ "$WRITE" -eq 1 ]]; then
    mkdir -p ~/.ssh && touch ~/.ssh/config && chmod 600 ~/.ssh/config
    if grep -qF "$marker" ~/.ssh/config; then
        echo "==> ssh config block already present -- leaving as-is"
    else
        printf '%s\n' "$block" >> ~/.ssh/config
        echo "==> appended Host $SSH_HOST_ALIAS block to ~/.ssh/config"
    fi
    echo ""
    echo "done -- connect with: ssh $SSH_HOST_ALIAS   (also scp $SSH_HOST_ALIAS:..., rsync, git)"
else
    echo "==> add this to ~/.ssh/config (or re-run with --write):"
    printf '%s\n' "$block"
fi
