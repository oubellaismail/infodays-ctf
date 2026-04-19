#!/usr/bin/env bash
# build-ctfd-image.sh — build and push the custom CTFd image with Blue Lock video background
#
# Usage:
#   bash scripts/build-ctfd-image.sh
#
# Requires: Docker authenticated to DOCR (run scripts/setup-docr.sh first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="registry.digitalocean.com/infodays-registry"
TAG="branded"
IMAGE="$REGISTRY/ctfd:$TAG"

echo "→ Building custom CTFd image: $IMAGE"
docker build \
  -f "$PROJECT_ROOT/Dockerfile.ctfd" \
  -t "$IMAGE" \
  "$PROJECT_ROOT"

echo "→ Pushing $IMAGE..."
docker push "$IMAGE"

echo "✓ Image pushed: $IMAGE"
echo ""
echo "Next: kubectl apply -f k8s/ctfd/deployment.yaml -n ctfd"
