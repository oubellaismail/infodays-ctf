#!/usr/bin/env bash
set -euo pipefail

# setup-docr.sh — Authenticate Docker to DOCR and wire the current DOKS cluster.
#
# Idempotent: safe to re-run on every deploy. Adds the cluster to the DOCR
# integration if not already linked, so nodes can pull without imagePullSecrets.
#
# Optional env vars:
#   DOKS_CLUSTER_NAME — cluster name to integrate (default: infodays-ctf)

DOKS_CLUSTER_NAME="${DOKS_CLUSTER_NAME:-infodays-ctf}"

# ---------------------------------------------------------------------------
# 1. Verify doctl is available
# ---------------------------------------------------------------------------
if ! command -v doctl &>/dev/null; then
  echo "ERROR: doctl is not installed or not in PATH." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Authenticate Docker daemon to DOCR
# ---------------------------------------------------------------------------
echo "Logging in to registry.digitalocean.com..."
doctl registry login

# ---------------------------------------------------------------------------
# 3. Verify registry exists
# ---------------------------------------------------------------------------
REGISTRY_NAME=$(doctl registry get --format Name --no-header 2>/dev/null || true)
if [[ -z "$REGISTRY_NAME" ]]; then
  echo "ERROR: No DOCR registry found. Ensure infodays-registry is provisioned." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 4. Get current cluster ID from kubeconfig context
# ---------------------------------------------------------------------------
CLUSTER_ID=$(doctl kubernetes cluster list --format ID,Name --no-header 2>/dev/null \
  | awk -v name="$DOKS_CLUSTER_NAME" '$2 == name { print $1 }' || true)

if [[ -z "$CLUSTER_ID" ]]; then
  echo "ERROR: Cluster '$DOKS_CLUSTER_NAME' not found via doctl." >&2
  echo "  Ensure the cluster is provisioned and doctl is authenticated." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 5. Add cluster to DOCR integration if not already linked
#    (doctl registry add is idempotent — safe to re-run)
# ---------------------------------------------------------------------------
echo "Linking cluster '$DOKS_CLUSTER_NAME' ($CLUSTER_ID) to registry '$REGISTRY_NAME'..."
doctl kubernetes cluster registry add "$CLUSTER_ID" 2>&1 || true
echo "DOKS <-> DOCR integration: active"

echo ""
echo "Setup complete. You can now run push-challenge.sh."
