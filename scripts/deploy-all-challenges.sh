#!/usr/bin/env bash
set -euo pipefail

# deploy-all-challenges.sh — Batch deploy all challenge manifests.
#
# Much more reliable than running deploy-challenge.sh per challenge because:
#   1. Creates/updates all CTFd challenges (HTTP only — no kubectl)
#   2. Updates ConfigMap ONCE with all manifests
#   3. Restarts controller ONCE
#   4. Runs bulk_spawn ONCE
#   5. Runs import_flags ONCE
#
# Usage:
#   bash scripts/deploy-all-challenges.sh [manifests-dir]
#
# Required environment:
#   CTFD_URL          — CTFd base URL (e.g., https://ctfd.infodays.net)
#   CTFD_ADMIN_TOKEN  — CTFd admin API token
#   CTF_MASTER_SECRET — master secret for flag derivation (unused here, kept for consistency)
#
# Optional:
#   CTFD_NAMESPACE     — namespace where controller runs (default: ctfd)
#   CHALLENGE_NAMESPACE — namespace for challenge pods (default: challenges)

CTFD_URL="${CTFD_URL:?ERROR: CTFD_URL not set}"
CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:?ERROR: CTFD_ADMIN_TOKEN not set}"

CTFD_NAMESPACE="${CTFD_NAMESPACE:-ctfd}"
CTFD_INTERNAL_URL="${CTFD_INTERNAL_URL:-http://ctfd-service.${CTFD_NAMESPACE}.svc.cluster.local}"
MANIFESTS_DIR="${1:-challenges/manifests}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

info()  { echo "▸ $*"; }
ok()    { echo "  ✔ $*"; }
fail()  { echo "  ✘ $*" >&2; exit 1; }

require_cmd() { command -v "$1" &>/dev/null || fail "$1 is required but not installed"; }
require_cmd kubectl
require_cmd python3

[ -d "$MANIFESTS_DIR" ] || fail "Manifests directory not found: $MANIFESTS_DIR"

cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Step 1: Ensure all CTFd challenges exist (pure HTTP, no kubectl)
# ---------------------------------------------------------------------------
info "Step 1: Creating/verifying all challenges in CTFd"

python3 - "$MANIFESTS_DIR" "$CTFD_URL" "$CTFD_ADMIN_TOKEN" <<'PYEOF'
import sys, os, json, urllib.request, urllib.error, yaml, glob

manifests_dir = sys.argv[1]
ctfd_url = sys.argv[2]
token = sys.argv[3]

def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"{ctfd_url}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
        method=method
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())

# Fetch existing challenges
existing = {}
data = api("/api/v1/challenges?per_page=200")
for ch in data.get("data", []):
    existing[ch["name"]] = ch["id"]

manifest_files = sorted(glob.glob(os.path.join(manifests_dir, "*.yaml")))
created = 0
skipped = 0

# Expand manifests into flat list of CTFd entries (bundle manifests → N entries)
entries = []
for fpath in manifest_files:
    with open(fpath) as f:
        m = yaml.safe_load(f)
    if not m:
        print(f"  SKIP (empty/invalid yaml): {fpath}")
        continue
    if "flags" in m:
        # Bundle manifest — each flag entry is a CTFd challenge
        for flag in m["flags"]:
            entries.append({
                "name": flag.get("name", ""),
                "category": flag.get("category", m.get("category", "")),
                "description": flag.get("description", m.get("description", f"Challenge: {flag.get('name', '')}")),
                "initial": int(flag.get("initial", m.get("initial", 500))),
                "minimum": int(flag.get("minimum", m.get("minimum", 50))),
                "decay": int(flag.get("decay", m.get("decay", 25))),
            })
    else:
        entries.append({
            "name": m.get("name", ""),
            "category": m.get("category", ""),
            "description": m.get("description", f"Challenge: {m.get('name', '')}"),
            "initial": int(m.get("initial", 500)),
            "minimum": int(m.get("minimum", 50)),
            "decay": int(m.get("decay", 25)),
        })

for entry in entries:
    name = entry["name"]
    category = entry["category"]
    if not name or not category:
        print(f"  SKIP (missing name/category): {entry}")
        continue

    if name in existing:
        print(f"  ✔ Already exists: {name} (id={existing[name]})")
        skipped += 1
    else:
        try:
            result = api("/api/v1/challenges", method="POST", body={
                "name": name,
                "category": category,
                "description": entry["description"],
                "value": entry["initial"],
                "initial": entry["initial"],
                "minimum": entry["minimum"],
                "decay": entry["decay"],
                "state": "visible",
                "type": "dynamic"
            })
            cid = result["data"]["id"]
            print(f"  ✔ Created: {name} (id={cid})")
            created += 1
        except Exception as e:
            print(f"  ✘ Failed to create {name}: {e}")

print(f"\n  Summary: {created} created, {skipped} already existed")
PYEOF

ok "CTFd challenge sync complete"

# ---------------------------------------------------------------------------
# Step 2: Update ConfigMap with ALL manifests (one operation)
# ---------------------------------------------------------------------------
info "Step 2: Updating challenge-manifests ConfigMap"

kubectl create configmap challenge-manifests \
  --from-file="$MANIFESTS_DIR" \
  -n "$CTFD_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

ok "ConfigMap updated"

# ---------------------------------------------------------------------------
# Step 3: Restart controller ONCE and wait
# ---------------------------------------------------------------------------
info "Step 3: Restarting controller API (single restart)"

kubectl rollout restart deployment/controller-api -n "$CTFD_NAMESPACE" >/dev/null
echo "  Waiting for rollout (up to 3 min)..."
kubectl rollout status deployment/controller-api -n "$CTFD_NAMESPACE" --timeout=180s || {
  echo "  Rollout timeout — checking for at least one Running pod..."
  READY=$(kubectl get pods -n "$CTFD_NAMESPACE" -l app=controller-api \
    --field-selector=status.phase=Running -o jsonpath='{.items}')
  [ "$READY" != "[]" ] || fail "No running controller-api pods after rollout timeout"
  echo "  At least one pod is Running — continuing"
}

ok "Controller API restarted"

# ---------------------------------------------------------------------------
# Step 4: Run bulk_spawn ONCE for all service challenges
# ---------------------------------------------------------------------------
info "Step 4: Running bulk_spawn (all service challenges)"

CONTROLLER_POD=$(kubectl get pods -n "$CTFD_NAMESPACE" -l app=controller-api \
  --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

[ -n "$CONTROLLER_POD" ] || fail "No running controller-api pod found"
echo "  Pod: $CONTROLLER_POD"

kubectl exec -n "$CTFD_NAMESPACE" "$CONTROLLER_POD" -- \
  env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
  python3 /app/bulk_spawn.py \
    --ctfd-url "$CTFD_INTERNAL_URL" \
    --token "$CTFD_ADMIN_TOKEN" 2>&1 | while IFS= read -r line; do
  echo "    $line"
done

ok "Bulk spawn complete"

# ---------------------------------------------------------------------------
# Step 5: Import flags ONCE for all challenges
# ---------------------------------------------------------------------------
info "Step 5: Importing flags for all challenges"

kubectl exec -n "$CTFD_NAMESPACE" "$CONTROLLER_POD" -- \
  env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
  python3 /app/import_flags.py \
    --ctfd-url "$CTFD_INTERNAL_URL" 2>&1 | while IFS= read -r line; do
  echo "    $line"
done

ok "Flag import complete"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "======================================"
echo " All challenges deployed"
echo "======================================"
echo "  CTFd:    $CTFD_URL"
echo "  Manifests: $MANIFESTS_DIR"
echo ""
echo "Service challenges: check challenge URLs at $CTFD_URL"
echo "Static challenges: players download per-team zip from CTFd modal"
