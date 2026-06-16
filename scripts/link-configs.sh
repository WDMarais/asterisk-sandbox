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
# Add 'asterisk' to the current user's primary group, then grant group-execute
# on each directory in the chain — scoped to the group rather than world.
USER_GROUP="$(id -gn)"
sudo usermod -aG "$USER_GROUP" asterisk
chmod g+x "$HOME"
chmod g+x "$REPO_ROOT"
chmod g+x "$REPO_DIR"
chmod g+r "$REPO_DIR"/*.conf
echo "permissions set (group: $USER_GROUP)"

echo "done — reload with: sudo asterisk -rx 'core reload'"
