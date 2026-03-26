#!/usr/bin/env bash
set -euo pipefail

REGISTRY="registry.digitalocean.com/infodays-registry"

usage() {
  echo "Usage: $0 <image-name> <dockerfile-dir> [tag]" >&2
  echo "  image-name     : alphanumeric, hyphens, dots only" >&2
  echo "  dockerfile-dir : directory containing Dockerfile" >&2
  echo "  tag            : image tag (default: latest)" >&2
  exit 1
}

# Validate required args
if [ $# -lt 2 ]; then
  usage
fi

IMAGE_NAME="$1"
DOCKERFILE_DIR="$2"
TAG="${3:-latest}"

# Validate image name (alphanumeric, hyphens, dots — no spaces or special chars)
if ! echo "${IMAGE_NAME}" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'; then
  echo "ERROR: Invalid image name '${IMAGE_NAME}'. Use alphanumeric characters, hyphens, or dots only." >&2
  exit 1
fi

# Validate tag
if ! echo "${TAG}" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'; then
  echo "ERROR: Invalid tag '${TAG}'. Use alphanumeric characters, hyphens, or dots only." >&2
  exit 1
fi

# Validate dockerfile directory exists
if [ ! -d "${DOCKERFILE_DIR}" ]; then
  echo "ERROR: '${DOCKERFILE_DIR}' is not a directory." >&2
  exit 1
fi

FULL_REF="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "Building ${FULL_REF} from ${DOCKERFILE_DIR} ..."
docker build -t "${FULL_REF}" "${DOCKERFILE_DIR}" || { echo "ERROR: docker build failed." >&2; exit 2; }

echo "Pushing ${FULL_REF} ..."
docker push "${FULL_REF}" || { echo "ERROR: docker push failed. Run setup-docr.sh first." >&2; exit 3; }

echo "Pushed: ${FULL_REF}"
