#!/usr/bin/env bash
# Generate a kubeconfig for use inside Docker containers on macOS/Linux.
# Embeds all cert data inline and remaps 127.0.0.1 → host.docker.internal
# so the container can reach the host's Kubernetes API server.
#
# Usage:
#   scripts/gen-kubeconfig.sh [context]        # defaults to current context
#
# Output: /tmp/kubeconfig-container (mounted into container at /app/kubeconfig)
#
# Run once before `docker compose up`, or re-run after `minikube start`.

set -euo pipefail

CONTEXT="${1:-$(kubectl config current-context)}"
OUT="/tmp/kubeconfig-container"

echo "Generating kubeconfig for context: $CONTEXT"

# --flatten embeds file-referenced certs inline
# Replace CA cert with insecure-skip-tls-verify so host.docker.internal TLS works
# (minikube CA cert SANs don't include host.docker.internal)
KUBECONFIG=~/.kube/config kubectl config view \
  --raw --flatten --minify --context="$CONTEXT" \
  | sed 's|https://127.0.0.1:|https://host.docker.internal:|g' \
  | sed 's|certificate-authority-data: .*|insecure-skip-tls-verify: true|' \
  > "$OUT"

echo "Written to $OUT ($(wc -l < "$OUT") lines)"
echo "Server: $(grep 'server:' "$OUT" | head -1 | xargs)"
