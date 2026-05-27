#!/usr/bin/env bash
set -euo pipefail

# deploy-all.sh — Full platform deployment: images → CTFd setup → all challenges.
#
# Efficient batch deployment: ConfigMap + controller restart + bulk_spawn + import_flags
# run ONCE for all challenges (not once per challenge like deploy-challenge.sh).
#
# Usage:
#   CTFD_URL=https://ctfd.infodays.net \
#   CTF_MASTER_SECRET=<secret> \
#   bash scripts/deploy-all.sh
#
# Required:
#   CTFD_URL            — CTFd base URL
#   CTF_MASTER_SECRET   — master secret for HMAC flag derivation
#
# Optional:
#   TEAMS_CSV           — path to teams CSV (default: data/teams.csv if it exists)
#   SKIP_IMAGES=1       — skip docker build/push (images already in DOCR)
#   SKIP_CTFD_SETUP=1   — skip CTFd initial setup (already configured)
#   CTFD_ADMIN_TOKEN    — override token (normally loaded from .ctfd.env)
#   CTFD_NAMESPACE      — namespace where controller runs (default: ctfd)
#   CHALLENGE_NAMESPACE — namespace for challenge pods (default: challenges)
#   MANIFESTS_DIR       — directory with challenge manifests (default: challenges/manifests)
#   ENV_FILE            — credentials file (default: .ctfd.env)

CTFD_URL="${CTFD_URL:?ERROR: CTFD_URL not set}"
CTF_MASTER_SECRET="${CTF_MASTER_SECRET:?ERROR: CTF_MASTER_SECRET not set}"

CTFD_NAMESPACE="${CTFD_NAMESPACE:-ctfd}"
CHALLENGE_NAMESPACE="${CHALLENGE_NAMESPACE:-challenges}"
MANIFESTS_DIR="${MANIFESTS_DIR:-challenges/manifests}"
ENV_FILE="${ENV_FILE:-.ctfd.env}"
SKIP_IMAGES="${SKIP_IMAGES:-0}"
SKIP_CTFD_SETUP="${SKIP_CTFD_SETUP:-0}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auto-detect teams CSV
if [[ -z "${TEAMS_CSV:-}" && -f "$PROJECT_ROOT/data/teams.csv" ]]; then
  TEAMS_CSV="$PROJECT_ROOT/data/teams.csv"
fi

# Load credentials from env file (token is written here by setup-ctfd.sh)
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  echo "INFO: Loaded credentials from $ENV_FILE"
fi
CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:-}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo; echo "▶ $*"; }
ok()    { echo "  ✔ $*"; }
fail()  { echo "  ✘ $*" >&2; exit 1; }
step()  { echo "  → $*"; }

require_cmd() {
  command -v "$1" &>/dev/null || fail "$1 is required but not installed"
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
info "Preflight"
require_cmd kubectl
require_cmd python3
require_cmd docker
step "kubectl context: $(kubectl config current-context 2>/dev/null || echo '<none>')"
step "Project root:    $PROJECT_ROOT"
step "Manifests dir:   $MANIFESTS_DIR"
step "CTFD URL:        $CTFD_URL"
ok "Preflight passed"

# Count manifests
MANIFEST_COUNT=$(ls "$PROJECT_ROOT/$MANIFESTS_DIR"/*.yaml 2>/dev/null | grep -v schema.yaml | wc -l | tr -d ' ')
step "Challenge manifests: $MANIFEST_COUNT"

# ===========================================================================
# Phase 1: Build & push all base images
# ===========================================================================
if [[ "$SKIP_IMAGES" == "1" ]]; then
  info "Phase 1/6: Image build/push — SKIPPED (SKIP_IMAGES=1)"
else
  info "Phase 1/6: Building and pushing base images to DOCR"

  # Authenticate Docker to DOCR first
  step "Authenticating to DOCR..."
  bash "$SCRIPT_DIR/setup-docr.sh"

  # Base images: directory name = image tag used in manifests
  # e.g. challenges/base-images/web → base:web
  IMAGE_DIRS=()
  for d in "$PROJECT_ROOT/challenges/base-images"/*/; do
    name="$(basename "$d")"
    # Skip static — it's a build-only artifact builder, not a runtime image
    [[ "$name" == "static" ]] && continue
    IMAGE_DIRS+=("$d")
  done

  step "Images to build: ${#IMAGE_DIRS[@]}"

  # Build and push in parallel (background jobs)
  PIDS=()
  LOGS=()
  for dir in "${IMAGE_DIRS[@]}"; do
    name="$(basename "$dir")"
    log="/tmp/push-${name}.log"
    LOGS+=("$log:$name")
    (
      bash "$SCRIPT_DIR/push-challenge.sh" "base" "$dir" "$name" > "$log" 2>&1
    ) &
    PIDS+=($!)
    step "Building base:$name (background pid $!)"
  done

  # Wait for all builds to complete
  step "Waiting for all image builds..."
  PUSH_ERRORS=0
  for i in "${!PIDS[@]}"; do
    pid="${PIDS[$i]}"
    log_entry="${LOGS[$i]}"
    log_file="${log_entry%%:*}"
    img_name="${log_entry##*:}"
    if wait "$pid"; then
      ok "base:$img_name pushed"
    else
      echo "  ✘ base:$img_name FAILED — see $log_file:" >&2
      cat "$log_file" >&2
      PUSH_ERRORS=$((PUSH_ERRORS + 1))
    fi
  done

  [[ $PUSH_ERRORS -eq 0 ]] || fail "$PUSH_ERRORS image build(s) failed"
  ok "All base images pushed"
fi

# ===========================================================================
# Phase 2: CTFd setup + team import
# ===========================================================================
if [[ "$SKIP_CTFD_SETUP" == "1" ]]; then
  info "Phase 2/6: CTFd setup — SKIPPED (SKIP_CTFD_SETUP=1)"
  [[ -n "$CTFD_ADMIN_TOKEN" ]] || fail "SKIP_CTFD_SETUP=1 but CTFD_ADMIN_TOKEN not set (check $ENV_FILE)"
else
  info "Phase 2/6: CTFd setup + team import"

  SETUP_ENV=(
    CTFD_URL="$CTFD_URL"
    CTFD_NAMESPACE="$CTFD_NAMESPACE"
    ENV_FILE="$ENV_FILE"
  )
  # Pass INGRESS_IP so setup-ctfd.sh can bypass DNS on fresh deploys
  [[ -n "${INGRESS_IP:-}" ]] && SETUP_ENV+=(INGRESS_IP="${INGRESS_IP}")
  # Pass controller key so setup-ctfd.sh can sync it into CTFd Configs table
  [[ -n "${CONTROLLER_KEY:-}" ]] && SETUP_ENV+=(CONTROLLER_KEY="${CONTROLLER_KEY}")
  if [[ -n "${TEAMS_CSV:-}" ]]; then
    SETUP_ENV+=(TEAMS_CSV="$TEAMS_CSV")
    step "Team import: $TEAMS_CSV"
  else
    step "Team import: skipped (no TEAMS_CSV)"
  fi

  env "${SETUP_ENV[@]}" bash "$SCRIPT_DIR/setup-ctfd.sh"

  # Reload token written by setup-ctfd.sh
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
  fi
  CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:-}"
  [[ -n "$CTFD_ADMIN_TOKEN" ]] || fail "setup-ctfd.sh completed but CTFD_ADMIN_TOKEN still not set"
  ok "CTFd ready, token loaded"
fi

# ===========================================================================
# Phase 3: Create all challenge entries in CTFd (idempotent, parallel)
# ===========================================================================
info "Phase 3/6: Creating challenge entries in CTFd"

PROJECT_ROOT="$PROJECT_ROOT" MANIFESTS_DIR="$MANIFESTS_DIR" \
CTFD_URL="$CTFD_URL" CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
python3 - <<PYEOF
import json
import urllib.request
import sys
import os
import yaml
import glob
import concurrent.futures

ctfd_url    = os.environ["CTFD_URL"]
admin_token = os.environ["CTFD_ADMIN_TOKEN"]
manifests_dir = os.path.join(os.environ["PROJECT_ROOT"], os.environ["MANIFESTS_DIR"])

headers = {
    "Authorization": f"Token {admin_token}",
    "Content-Type":  "application/json",
}

def api_get(path):
    req = urllib.request.Request(
        f"{ctfd_url}{path}", headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def api_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{ctfd_url}{path}", data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# Fetch existing challenges (name → id)
existing = {}
for ch in api_get("/api/v1/challenges?per_page=500").get("data", []):
    existing[ch["name"]] = ch["id"]
print(f"  Existing CTFd challenges: {len(existing)}", flush=True)

# Load manifests
manifests = []
for path in sorted(glob.glob(f"{manifests_dir}/*.yaml")):
    if os.path.basename(path) == "schema.yaml":
        continue
    with open(path) as f:
        m = yaml.safe_load(f)
    if m:
        manifests.append(m)

print(f"  Manifests found: {len(manifests)}", flush=True)

def create_one(m):
    name = m.get("name", "")
    if name in existing:
        return ("skipped", name, existing[name])
    desc = m.get("description", f"Challenge: {name}")
    initial = int(m.get("initial", 500))
    minimum = int(m.get("minimum", 50))
    decay   = int(m.get("decay", 25))
    body = {
        "name":        name,
        "category":    m.get("category", "misc"),
        "description": desc,
        "value":       initial,
        "initial":     initial,
        "minimum":     minimum,
        "decay":       decay,
        "state":       "visible",
        "type":        "dynamic",
    }
    try:
        resp = api_post("/api/v1/challenges", body)
        cid  = resp["data"]["id"]
        return ("created", name, cid)
    except Exception as e:
        return ("error", name, str(e))

created = skipped = errors = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    for status, name, info in ex.map(create_one, manifests):
        if status == "created":
            print(f"  ✔ Created: {name} (id={info})", flush=True)
            created += 1
        elif status == "skipped":
            print(f"  - Exists:  {name} (id={info})", flush=True)
            skipped += 1
        else:
            print(f"  ✘ Error:   {name}: {info}", file=sys.stderr, flush=True)
            errors += 1

print(f"  Done: {created} created, {skipped} already existed, {errors} errors", flush=True)
if errors:
    sys.exit(1)
PYEOF

ok "All challenge entries in CTFd"

# ===========================================================================
# Phase 4: Update ConfigMap + restart controller
# ===========================================================================
info "Phase 4/6: Updating challenge-manifests ConfigMap"

kubectl create configmap challenge-manifests \
  --from-file="$PROJECT_ROOT/$MANIFESTS_DIR" \
  -n "$CTFD_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
ok "ConfigMap updated"

step "Restarting controller-api..."
kubectl rollout restart deployment/controller-api -n "$CTFD_NAMESPACE" >/dev/null
kubectl rollout status deployment/controller-api -n "$CTFD_NAMESPACE" --timeout=120s >/dev/null
ok "Controller API restarted"

# ===========================================================================
# Phase 5: bulk_spawn — create K8s resources for all teams × service challenges
# ===========================================================================
info "Phase 5/6: Running bulk_spawn (all teams × all service challenges)"

# Run provisioning inside the scaled-to-zero provisioner pod. The always-on
# controller-api pod keeps runtime-only RBAC and cannot read challenge secrets.
cleanup_provisioner() {
  kubectl scale deployment/controller-provisioner -n "$CTFD_NAMESPACE" --replicas=0 >/dev/null 2>&1 || true
}
trap cleanup_provisioner EXIT

kubectl apply -f "$PROJECT_ROOT/k8s/controller/provisioner-deployment.yaml" >/dev/null
kubectl scale deployment/controller-provisioner -n "$CTFD_NAMESPACE" --replicas=1 >/dev/null
kubectl rollout status deployment/controller-provisioner -n "$CTFD_NAMESPACE" --timeout=120s >/dev/null

PROVISIONER_POD=""
for _i in $(seq 1 12); do
  PROVISIONER_POD=$(kubectl get pods -n "$CTFD_NAMESPACE" -l app=controller-provisioner \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  [[ -n "$PROVISIONER_POD" ]] && break
  sleep 5
done
[[ -n "$PROVISIONER_POD" ]] || fail "No running controller-provisioner pod found in namespace '$CTFD_NAMESPACE'"
step "Using provisioner pod: $PROVISIONER_POD"

# Use internal service URL — ctfd.infodays.net is not reachable from within the cluster
# (hairpin NAT issue with DOKS load balancer). Internal URL works because NetworkPolicy
# allow-controller-egress-ctfd permits controller-api → ctfd pods on port 8000.
CTFD_INTERNAL_URL="http://ctfd-service.${CTFD_NAMESPACE}.svc.cluster.local"

# Ensure tcp-services ConfigMap exists in ingress-nginx (required for TCP challenge port mapping)
kubectl create configmap tcp-services -n ingress-nginx \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1 || true

kubectl exec -n "$CTFD_NAMESPACE" "$PROVISIONER_POD" -- \
  env \
    CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
    CTF_MASTER_SECRET="$CTF_MASTER_SECRET" \
  python3 /app/bulk_spawn.py \
    --ctfd-url "$CTFD_INTERNAL_URL" \
    --token   "$CTFD_ADMIN_TOKEN" \
  2>&1 | while IFS= read -r line; do echo "    $line"; done

ok "bulk_spawn complete"

# ===========================================================================
# Phase 6: import_flags — one team flag row per challenge in CTFd
# ===========================================================================
info "Phase 6/6: Importing team-derived flags into CTFd"

kubectl exec -n "$CTFD_NAMESPACE" "$PROVISIONER_POD" -- \
  env \
    CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
    CTF_MASTER_SECRET="$CTF_MASTER_SECRET" \
  python3 /app/import_flags.py \
    --ctfd-url "$CTFD_INTERNAL_URL" \
  2>&1 | while IFS= read -r line; do echo "    $line"; done

ok "Flag import complete"

# ===========================================================================
# Done
# ===========================================================================
echo
echo "======================================"
echo " Full deployment complete"
echo "======================================"
echo "  CTFd:       $CTFD_URL"
echo "  Challenges: $MANIFEST_COUNT"
echo "  Creds:      $ENV_FILE"
echo
echo "Next steps:"
echo "  • Open $CTFD_URL/admin/config and set event start/end times"
echo "  • Run the pre-event checklist: docs/pre-event-checklist.md"
echo "  • Load test: see docs/pre-event-checklist.md → Load test section"
echo
