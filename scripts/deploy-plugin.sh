#!/usr/bin/env bash
# deploy-plugin.sh — push local ctfd-plugin/ changes to the cluster and restart CTFd
#
# Usage:
#   bash scripts/deploy-plugin.sh
#
# What it does:
#   1. Updates the 5 split ConfigMaps that CTFd mounts (ctfd-plugin-init, -js, -css, logos)
#   2. Restarts the CTFd deployment so pods pick up the new code

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN="$PROJECT_ROOT/ctfd-plugin"
NS="ctfd"

echo "→ Updating plugin ConfigMaps..."
kubectl create configmap ctfd-plugin-init \
  --from-file=__init__.py="$PLUGIN/__init__.py" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl create configmap ctfd-plugin-js \
  --from-file=plugin.js="$PLUGIN/assets/plugin.js" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl create configmap ctfd-plugin-css \
  --from-file=style.css="$PLUGIN/assets/style.css" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl create configmap ctfd-plugin-logo-dark \
  --from-file=logo-dark.png="$PLUGIN/assets/logo-dark.png" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl create configmap ctfd-plugin-logo-light \
  --from-file=logo-light.png="$PLUGIN/assets/logo-light.png" \
  -n "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "→ Restarting CTFd..."
kubectl rollout restart deployment/ctfd -n "$NS"
kubectl rollout status deployment/ctfd -n "$NS" --timeout=300s

echo "✓ Plugin deployed"
