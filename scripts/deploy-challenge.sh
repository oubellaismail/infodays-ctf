#!/usr/bin/env bash
set -euo pipefail

# deploy-challenge.sh — One-command challenge deployment.
#
# Takes a challenge manifest YAML and:
#   1. Validates the manifest against the schema
#   2. Creates the challenge in CTFd (if not exists)
#   3. Updates the challenge-manifests ConfigMap
#   4. Restarts the controller API (to pick up new manifests)
#   5. Runs bulk_spawn to create K8s resources for all teams
#   6. Imports per-team flags into CTFd
#
# Usage:
#   bash scripts/deploy-challenge.sh challenges/manifests/web-sqli.yaml
#
# Required environment:
#   CTFD_URL             — CTFd base URL (e.g., https://ctfd.infodays.net)
#   CTFD_ADMIN_TOKEN     — CTFd admin API token
#   CTF_MASTER_SECRET    — master secret for flag derivation
#
# Optional:
#   CTFD_NAMESPACE       — namespace where controller runs (default: ctfd)
#   CHALLENGE_NAMESPACE  — namespace for challenge pods (default: challenges)
#   MANIFESTS_DIR        — directory with all manifests (default: challenges/manifests)

CTFD_URL="${CTFD_URL:?ERROR: CTFD_URL not set}"
CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:?ERROR: CTFD_ADMIN_TOKEN not set}"
CTF_MASTER_SECRET="${CTF_MASTER_SECRET:?ERROR: CTF_MASTER_SECRET not set}"

CTFD_NAMESPACE="${CTFD_NAMESPACE:-ctfd}"
CHALLENGE_NAMESPACE="${CHALLENGE_NAMESPACE:-challenges}"
MANIFESTS_DIR="${MANIFESTS_DIR:-challenges/manifests}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "▸ $*"; }
ok()    { echo "  ✔ $*"; }
fail()  { echo "  ✘ $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" &>/dev/null || fail "$1 is required but not installed"
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
require_cmd kubectl
require_cmd python3

MANIFEST_FILE="${1:?Usage: $0 <manifest.yaml>}"
[ -f "$MANIFEST_FILE" ] || fail "File not found: $MANIFEST_FILE"

# Parse manifest fields using python (avoids yq dependency)
read_field() {
  python3 -c "
import yaml, sys
with open('$MANIFEST_FILE') as f:
    m = yaml.safe_load(f)
print(m.get('$1', ''))
"
}

CHALLENGE_ID="$(read_field id)"
CHALLENGE_NAME="$(read_field name)"
CHALLENGE_CATEGORY="$(read_field category)"
CHALLENGE_TYPE="$(read_field type)"
CHALLENGE_POINTS="$(read_field points)"
CHALLENGE_PORT="$(read_field port)"
CHALLENGE_IMAGE="$(read_field image)"
CHALLENGE_DESC="$(read_field description)"
CHALLENGE_INITIAL="$(read_field initial)"
CHALLENGE_MINIMUM="$(read_field minimum)"
CHALLENGE_DECAY="$(read_field decay)"

[ -n "$CHALLENGE_ID" ]       || fail "Manifest missing 'id'"
[ -n "$CHALLENGE_NAME" ]     || fail "Manifest missing 'name'"
[ -n "$CHALLENGE_CATEGORY" ] || fail "Manifest missing 'category'"
[ -n "$CHALLENGE_TYPE" ]     || fail "Manifest missing 'type'"

# Dynamic scoring defaults: 500 initial, 50 minimum, 25 solves to reach minimum
CHALLENGE_INITIAL="${CHALLENGE_INITIAL:-500}"
CHALLENGE_MINIMUM="${CHALLENGE_MINIMUM:-50}"
CHALLENGE_DECAY="${CHALLENGE_DECAY:-25}"

# Service challenges require image + port; static challenges do not
if [ "$CHALLENGE_TYPE" != "static" ]; then
  [ -n "$CHALLENGE_PORT" ]   || fail "Manifest missing 'port'"
  [ -n "$CHALLENGE_IMAGE" ]  || fail "Manifest missing 'image'"
fi

info "Deploying challenge: $CHALLENGE_NAME ($CHALLENGE_ID)"
echo "  category=$CHALLENGE_CATEGORY  type=$CHALLENGE_TYPE  scoring=${CHALLENGE_INITIAL}→${CHALLENGE_MINIMUM} (decay=${CHALLENGE_DECAY})"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Ensure manifest is in the manifests directory
# ---------------------------------------------------------------------------
info "Step 1/6: Ensuring manifest is in $MANIFESTS_DIR"

TARGET_FILE="$MANIFESTS_DIR/$CHALLENGE_ID.yaml"
if [ "$(realpath "$MANIFEST_FILE")" != "$(realpath "$TARGET_FILE")" ]; then
  cp "$MANIFEST_FILE" "$TARGET_FILE"
  ok "Copied to $TARGET_FILE"
else
  ok "Already in place"
fi

# ---------------------------------------------------------------------------
# Step 2: Create challenge in CTFd (idempotent)
# ---------------------------------------------------------------------------
info "Step 2/6: Creating challenge in CTFd"

# Check if challenge already exists by name
EXISTING=$(python3 -c "
import json, urllib.request
req = urllib.request.Request(
    '${CTFD_URL}/api/v1/challenges?per_page=100',
    headers={'Authorization': 'Token ${CTFD_ADMIN_TOKEN}', 'Content-Type': 'application/json'}
)
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
for ch in data.get('data', []):
    if ch.get('name') == '''${CHALLENGE_NAME}''':
        print(ch['id'])
        break
" 2>/dev/null || true)

if [ -n "$EXISTING" ]; then
  ok "Already exists in CTFd (id=$EXISTING)"
else
  # Create the challenge with dynamic scoring
  DESC="${CHALLENGE_DESC:-Challenge: ${CHALLENGE_NAME}}"
  CTFD_CHALLENGE_ID=$(python3 -c "
import json, urllib.request, sys
body = json.dumps({
    'name': sys.argv[1],
    'category': sys.argv[2],
    'description': sys.argv[3],
    'value': int(sys.argv[4]),
    'initial': int(sys.argv[4]),
    'minimum': int(sys.argv[5]),
    'decay': int(sys.argv[6]),
    'state': 'visible',
    'type': 'dynamic'
}).encode()
req = urllib.request.Request(
    '${CTFD_URL}/api/v1/challenges',
    data=body,
    headers={'Authorization': 'Token ${CTFD_ADMIN_TOKEN}', 'Content-Type': 'application/json'},
    method='POST'
)
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
print(data['data']['id'])
" "$CHALLENGE_NAME" "$CHALLENGE_CATEGORY" "$DESC" "$CHALLENGE_INITIAL" "$CHALLENGE_MINIMUM" "$CHALLENGE_DECAY")
  ok "Created in CTFd (id=$CTFD_CHALLENGE_ID)"
  EXISTING="$CTFD_CHALLENGE_ID"
fi

# ===========================================================================
# Static challenges: per-team zips served by plugin, team-derived flags
# ===========================================================================
if [ "$CHALLENGE_TYPE" = "static" ]; then

  # ---- Step 3: Update ConfigMap (so import_flags picks up the manifest) ----
  info "Step 3/5: Updating challenge-manifests ConfigMap"

  kubectl create configmap challenge-manifests \
    --from-file="$MANIFESTS_DIR" \
    -n "$CTFD_NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  ok "ConfigMap updated"

  # ---- Step 4: Restart controller API (to reload manifest cache) ----
  info "Step 4/5: Restarting controller API"

  kubectl rollout restart deployment/controller-api -n "$CTFD_NAMESPACE" >/dev/null
  kubectl rollout status deployment/controller-api -n "$CTFD_NAMESPACE" --timeout=60s >/dev/null

  ok "Controller API restarted"

  # ---- Step 5: Import team-derived flag into CTFd ----
  info "Step 5/5: Importing team-derived flag into CTFd"

  CONTROLLER_POD=$(kubectl get pods -n "$CTFD_NAMESPACE" -l app=controller-api \
    --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

  [ -n "$CONTROLLER_POD" ] || fail "No running controller-api pod found"

  kubectl exec -n "$CTFD_NAMESPACE" "$CONTROLLER_POD" -- \
    env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
    python3 /app/import_flags.py \
      --ctfd-url "$CTFD_URL" 2>&1 | while IFS= read -r line; do
    echo "    $line"
  done

  ok "Team-derived flag imported"

  # ---- Summary ----
  echo ""
  echo "======================================"
  echo " Static challenge deployed: $CHALLENGE_NAME"
  echo "======================================"
  echo "  ID:       $CHALLENGE_ID"
  echo "  Category: $CHALLENGE_CATEGORY"
  echo "  Type:     static (per-team file download)"
  echo "  Scoring:  dynamic ($CHALLENGE_INITIAL → $CHALLENGE_MINIMUM, decay=$CHALLENGE_DECAY)"
  echo "  Download: /download/$CHALLENGE_ID (plugin endpoint, per-team zip)"
  echo ""
  echo "Players download the file from the challenge modal (per-team zip with unique flag)."
  exit 0
fi

# ===========================================================================
# Service challenges: K8s pods + controller integration
# ===========================================================================

# ---------------------------------------------------------------------------
# Step 3: Update challenge-manifests ConfigMap
# ---------------------------------------------------------------------------
info "Step 3/6: Updating challenge-manifests ConfigMap"

kubectl create configmap challenge-manifests \
  --from-file="$MANIFESTS_DIR" \
  -n "$CTFD_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

ok "ConfigMap updated"

# ---------------------------------------------------------------------------
# Step 4: Restart controller API (to reload manifest cache)
# ---------------------------------------------------------------------------
info "Step 4/6: Restarting controller API"

kubectl rollout restart deployment/controller-api -n "$CTFD_NAMESPACE" >/dev/null
kubectl rollout status deployment/controller-api -n "$CTFD_NAMESPACE" --timeout=60s >/dev/null

ok "Controller API restarted"

# ---------------------------------------------------------------------------
# Step 5: Run bulk_spawn (create K8s resources for all teams)
# ---------------------------------------------------------------------------
info "Step 5/6: Running bulk_spawn (creating K8s resources for all teams)"

# Run bulk_spawn inside the controller pod (it has K8s credentials and manifests)
CONTROLLER_POD=$(kubectl get pods -n "$CTFD_NAMESPACE" -l app=controller-api \
  --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

[ -n "$CONTROLLER_POD" ] || fail "No running controller-api pod found"

kubectl exec -n "$CTFD_NAMESPACE" "$CONTROLLER_POD" -- \
  env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
  python3 /app/bulk_spawn.py \
    --ctfd-url "$CTFD_URL" \
    --token "$CTFD_ADMIN_TOKEN" 2>&1 | while IFS= read -r line; do
  echo "    $line"
done

ok "Bulk spawn complete"

# ---------------------------------------------------------------------------
# Step 6: Import per-team flags into CTFd
# ---------------------------------------------------------------------------
info "Step 6/6: Importing per-team flags into CTFd"

kubectl exec -n "$CTFD_NAMESPACE" "$CONTROLLER_POD" -- \
  env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
  python3 /app/import_flags.py \
    --ctfd-url "$CTFD_URL" 2>&1 | while IFS= read -r line; do
  echo "    $line"
done

ok "Flag import complete"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================"
echo " Challenge deployed: $CHALLENGE_NAME"
echo "======================================"
echo "  ID:       $CHALLENGE_ID"
echo "  Category: $CHALLENGE_CATEGORY"
echo "  Type:     $CHALLENGE_TYPE"
echo "  Scoring:  dynamic ($CHALLENGE_INITIAL → $CHALLENGE_MINIMUM, decay=$CHALLENGE_DECAY)"

if [ "$CHALLENGE_TYPE" = "http" ]; then
  echo "  URL:      https://team-{ID}-${CHALLENGE_ID}.challenges.infodays.net"
else
  echo "  Access:   nc challenges.infodays.net {port}"
fi

echo ""
echo "Teams can now start this challenge from the CTFd UI."
