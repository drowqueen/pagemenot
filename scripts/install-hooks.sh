#!/bin/bash
# Install git hooks. Run once after cloning: bash scripts/install-hooks.sh

HOOKS_DIR="$(git rev-parse --show-toplevel)/.git/hooks"

install_hook() {
    local name=$1
    local src="scripts/hooks/$name"
    local dst="$HOOKS_DIR/$name"
    cp "$src" "$dst"
    chmod +x "$dst"
    echo "✅ Installed $name"
}

install_hook pre-commit
install_hook pre-push

echo "Done."
