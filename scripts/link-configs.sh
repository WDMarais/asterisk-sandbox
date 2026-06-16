#!/bin/bash
# Symlink repo config files into /etc/asterisk.
# Only links files explicitly managed here; leaves the rest of /etc/asterisk untouched.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$REPO_ROOT/asterisk"
ETC_DIR="/etc/asterisk"

files=(
    pjsip.conf
    extensions.conf
    http.conf
    queues.conf
)

for f in "${files[@]}"; do
    sudo ln -sf "$REPO_DIR/$f" "$ETC_DIR/$f"
    echo "linked $f"
done

# Asterisk runs as the 'asterisk' user and must traverse the symlink target path.
# Use SUDO_USER to get the real user's group when running under sudo.
ACTUAL_USER="${SUDO_USER:-$(id -un)}"
USER_GROUP="$(id -gn "$ACTUAL_USER")"
USER_HOME="$(eval echo "~$ACTUAL_USER")"
sudo usermod -aG "$USER_GROUP" asterisk
chmod g+x "$USER_HOME"
chmod g+x "$REPO_ROOT"
chmod g+x "$REPO_DIR"
chmod g+r "$REPO_DIR"/*.conf
echo "permissions set (group: $USER_GROUP)"

echo "done -- reload with: sudo systemctl restart asterisk"
