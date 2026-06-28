#!/bin/bash
# Symlink the tracked git hooks into .git/hooks so they run locally.
# Re-run any time; safe and idempotent. Run from anywhere in the repo.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hooks_src="$repo_root/scripts/hooks"
hooks_dst="$repo_root/.git/hooks"

ln -sf "../../scripts/hooks/pre-commit" "$hooks_dst/pre-commit"
echo "installed pre-commit hook -> scripts/hooks/pre-commit"
