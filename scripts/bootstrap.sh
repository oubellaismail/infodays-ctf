#!/usr/bin/env bash
set -euo pipefail

# bootstrap.sh — Full platform bootstrap: infra → images → K8s stack → CTFd → challenges.
#
# Idempotent: safe to re-run at any stage. Each phase is guarded by readiness checks.
#
# Usage (first run):
#   CTFD_URL=https://ctfd.infodays.net \
#   CTF_MASTER_SECRET=<secret> \
#   CONTROLLER_KEY=<key> \
#   bash scripts/bootstrap.sh
#
# Usage (resume from K8s stack onward — infra already up):
#   CTFD_URL=https://ctfd.infodays.net \
#   CTF_MASTER_SECRET=<secret> \
#   CONTROLLER_KEY=<key> \
#   SKIP_TERRAFORM=1 \
#   bash scripts/bootstrap.sh
#
# Usage (resume from CTFd setup onward — K8s stack already deployed):
#   CTFD_URL=https://ctfd.infodays.net \
#   CTF_MASTER_SECRET=<secret> \
#   CONTROLLER_KEY=<key> \
#   SKIP_TERRAFORM=1 SKIP_K8S_STACK=1 \
#   bash scripts/bootstrap.sh
#
# Required:
#   CTFD_URL            — CTFd base URL
#   CTF_MASTER_SECRET   — master HMAC secret (must match value in k8s/ctfd/secrets.local.yaml)
#
# Optional:
#   CONTROLLER_KEY      — X-Controller-Key shared secret (auto-generated if not set)
#   TEAMS_CSV           — CSV for team import (default: data/teams.csv if exists)
#   SKIP_TERRAFORM=1    — skip terraform provisioning
#   SKIP_K8S_STACK=1    — skip K8s stack deployment (implies SKIP_TERRAFORM=1)
#   SKIP_IMAGES=1       — skip docker build/push (pass-through to deploy-all.sh)
#   CTFD_NAMESPACE      — namespace for CTFd (default: ctfd)
#   CHALLENGE_NAMESPACE — namespace for challenges (default: challenges)
#   ENV_FILE            — credentials file (default: .ctfd.env)
#   TF_DIR              — terraform directory (default: infra/terraform)

CTFD_URL="${CTFD_URL:?ERROR: CTFD_URL not set}"
CTF_MASTER_SECRET="${CTF_MASTER_SECRET:?ERROR: CTF_MASTER_SECRET not set}"

CTFD_NAMESPACE="${CTFD_NAMESPACE:-ctfd}"
CHALLENGE_NAMESPACE="${CHALLENGE_NAMESPACE:-challenges}"
ENV_FILE="${ENV_FILE:-.ctfd.env}"
TF_DIR="${TF_DIR:-infra/terraform}"

SKIP_TERRAFORM="${SKIP_TERRAFORM:-0}"
SKIP_K8S_STACK="${SKIP_K8S_STACK:-0}"
SKIP_IMAGES="${SKIP_IMAGES:-0}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auto-detect teams CSV
if [[ -z "${TEAMS_CSV:-}" && -f "$PROJECT_ROOT/data/teams.csv" ]]; then
  TEAMS_CSV="$PROJECT_ROOT/data/teams.csv"
fi

# Load CONTROLLER_KEY from ENV_FILE if not provided (keeps it stable across re-runs)
if [[ -z "${CONTROLLER_KEY:-}" && -f "$ENV_FILE" ]]; then
  SAVED_KEY=$(grep "^CONTROLLER_KEY=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
  [[ -n "$SAVED_KEY" ]] && CONTROLLER_KEY="$SAVED_KEY" && echo "INFO: Loaded CONTROLLER_KEY from $ENV_FILE (value hidden)"
fi

# Generate CONTROLLER_KEY if not provided
if [[ -z "${CONTROLLER_KEY:-}" ]]; then
  CONTROLLER_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  echo "INFO: Generated CONTROLLER_KEY — saved to $ENV_FILE (value hidden from logs)"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "▶  $*"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()    { echo "  ✔ $*"; }
fail()  { echo "  ✘ $*" >&2; exit 1; }
step()  { echo "  → $*"; }

require_cmd() {
  command -v "$1" &>/dev/null || fail "$1 is required but not installed"
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
info "Preflight"
require_cmd kubectl
require_cmd docker
require_cmd python3
require_cmd doctl
[[ "$SKIP_TERRAFORM" == "1" ]] || require_cmd terraform

step "Project root:  $PROJECT_ROOT"
step "CTFd URL:      $CTFD_URL"
step "Namespace:     $CTFD_NAMESPACE / $CHALLENGE_NAMESPACE"
ok "Preflight passed"

# ============================================================================
# Phase 1: Terraform — provision cluster + DNS + ingress + cert-manager
# ============================================================================
if [[ "$SKIP_TERRAFORM" == "1" || "$SKIP_K8S_STACK" == "1" ]]; then
  info "Phase 1/7: Terraform — SKIPPED"
else
  info "Phase 1/7: Terraform provisioning (3-pass)"

  cd "$PROJECT_ROOT"

  # Check if cluster already exists
  CLUSTER_EXISTS=$(doctl kubernetes cluster list --format Name --no-header 2>/dev/null | grep -c "infodays-ctf" || true)
  if [[ "$CLUSTER_EXISTS" -gt 0 ]]; then
    step "Cluster infodays-ctf already exists — running terraform apply to sync state"
  else
    step "No cluster found — provisioning from scratch"
  fi

  # Init (safe to re-run)
  step "terraform init..."
  terraform -chdir="$TF_DIR" init \
    -backend-config="access_key=${AWS_ACCESS_KEY_ID:?ERROR: AWS_ACCESS_KEY_ID not set}" \
    -backend-config="secret_key=${AWS_SECRET_ACCESS_KEY:?ERROR: AWS_SECRET_ACCESS_KEY not set}" \
    -reconfigure 2>&1 | tail -5

  # Pass 1: cluster + registry
  step "Pass 1: cluster + registry..."
  terraform -chdir="$TF_DIR" apply \
    -target=digitalocean_kubernetes_cluster.infodays \
    -target=digitalocean_container_registry.infodays \
    -auto-approve 2>&1 | tail -10

  # Save kubeconfig
  step "Saving kubeconfig..."
  doctl kubernetes cluster kubeconfig save infodays-ctf

  # Pass 2: namespaces + helm (cert-manager CRDs must exist before pass 3)
  step "Pass 2: namespaces + helm releases..."
  terraform -chdir="$TF_DIR" apply \
    -target=kubernetes_namespace.cert_manager \
    -target=kubernetes_namespace.ctfd \
    -target=kubernetes_namespace.challenges \
    -target=kubernetes_namespace.monitoring \
    -target=kubernetes_namespace.ingress_nginx \
    -target=helm_release.ingress_nginx \
    -target=helm_release.cert_manager \
    -auto-approve 2>&1 | tail -10

  # Pass 3: everything else (DNS, DOCR pull secrets, network policies, etc.)
  step "Pass 3: all remaining resources..."
  terraform -chdir="$TF_DIR" apply -auto-approve 2>&1 | tail -10

  ok "Terraform provisioning complete"
  cd "$PROJECT_ROOT"
fi

# ============================================================================
# Phase 2: Build & push controller images
# ============================================================================
info "Phase 2/7: Building controller images"

# Authenticate Docker to DOCR
step "Authenticating to DOCR..."
bash "$SCRIPT_DIR/setup-docr.sh"

# After a registry wipe (all tags deleted), DOCR keeps repositories in a
# "ghost" state that is invisible in list but counted against the plan limit.
# Pushing fails with "limit is 1" until the ghost is cleared.
# Fix: wait for any active GC to finish (GC locks registry read-only), then
# explicitly delete ghost repositories via the DO API.
step "Checking for active GC (registry must not be read-only before pushing)..."
for i in $(seq 1 36); do  # wait up to 3 min (36 × 5s)
  GC_ACTIVE=$(doctl registry garbage-collection get-active \
    --format Status --no-header 2>/dev/null || echo "")
  if [[ -z "$GC_ACTIVE" ]]; then
    break
  fi
  step "  GC in progress ($GC_ACTIVE) — waiting 5s... ($i/36)"
  sleep 5
done

DO_TOKEN="${DIGITALOCEAN_TOKEN:-$(python3 -c "
import re
with open('$PROJECT_ROOT/infra/terraform/terraform.tfvars') as f:
    m = re.search(r'do_token\s*=\s*\"([^\"]+)\"', f.read())
    print(m.group(1) if m else '')
" 2>/dev/null)}"
REGISTRY_NAME="infodays-registry"

step "Removing any ghost repositories (0-tag repos that block plan limits)..."
REPO_NAMES=$(curl -s \
  -H "Authorization: Bearer ${DO_TOKEN}" \
  "https://api.digitalocean.com/v2/registry/${REGISTRY_NAME}/repositoriesV2" \
  2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
for r in data.get('repositories', []):
    # Only delete truly empty (ghost) repos — never delete repos that have tags
    if int(r.get('tag_count', 0)) == 0:
        print(r['name'])
" 2>/dev/null || true)

if [[ -n "$REPO_NAMES" ]]; then
  for repo in $REPO_NAMES; do
    step "Deleting ghost repository: $repo"
    curl -s -X DELETE \
      -H "Authorization: Bearer ${DO_TOKEN}" \
      "https://api.digitalocean.com/v2/registry/${REGISTRY_NAME}/repositories/${repo}" \
      >/dev/null 2>&1 || true
  done
  sleep 3  # let the deletion propagate — NO GC needed (avoids read-only lockout)
  ok "Ghost repositories removed"
else
  ok "No ghost repositories found"
fi

# Re-authenticate Docker (token may be stale after waiting)
doctl registry login 2>/dev/null || true

REGISTRY="registry.digitalocean.com/infodays-registry"

# Build controller-api
step "Building base:controller-api..."
docker build -t "${REGISTRY}/base:controller-api" "$PROJECT_ROOT/controller" \
  -f "$PROJECT_ROOT/controller/Dockerfile" 2>&1 | tail -3
docker push "${REGISTRY}/base:controller-api" 2>&1 | tail -3
ok "base:controller-api pushed"

# Build controller-daemon
step "Building base:controller-daemon..."
docker build -t "${REGISTRY}/base:controller-daemon" "$PROJECT_ROOT/controller" \
  -f "$PROJECT_ROOT/controller/daemon.Dockerfile" 2>&1 | tail -3
docker push "${REGISTRY}/base:controller-daemon" 2>&1 | tail -3
ok "base:controller-daemon pushed"

# ============================================================================
# Phase 3: Deploy K8s stack
# ============================================================================
if [[ "$SKIP_K8S_STACK" == "1" ]]; then
  info "Phase 3/7: K8s stack — SKIPPED"
else
  info "Phase 3/7: Deploying K8s stack"

  K8S="$PROJECT_ROOT/k8s"

  # ── Secrets ──────────────────────────────────────────────────────────────
  step "Applying CTFd secrets..."
  kubectl apply -f "$K8S/ctfd/secrets.local.yaml"

  step "Creating controller-key secret..."
  kubectl create secret generic controller-key \
    --from-literal=CONTROLLER_KEY="$CONTROLLER_KEY" \
    -n "$CTFD_NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -
  ok "Secrets applied"

  # ── Plugin ConfigMaps (must exist before CTFd starts) ────────────────────
  step "Creating plugin ConfigMaps..."
  PLUGIN="$PROJECT_ROOT/ctfd-plugin"
  kubectl create configmap ctfd-plugin-init \
    --from-file=__init__.py="$PLUGIN/__init__.py" \
    -n "$CTFD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create configmap ctfd-plugin-js \
    --from-file=plugin.js="$PLUGIN/assets/plugin.js" \
    -n "$CTFD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create configmap ctfd-plugin-css \
    --from-file=style.css="$PLUGIN/assets/style.css" \
    -n "$CTFD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create configmap ctfd-plugin-logo-dark \
    --from-file=logo-dark.png="$PLUGIN/assets/logo-dark.png" \
    -n "$CTFD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create configmap ctfd-plugin-logo-light \
    --from-file=logo-light.png="$PLUGIN/assets/logo-light.png" \
    -n "$CTFD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  ok "Plugin ConfigMaps applied"

  # ── Services ─────────────────────────────────────────────────────────────
  step "Applying services..."
  kubectl apply -f "$K8S/ctfd/services.yaml"

  # ── Stateful components ───────────────────────────────────────────────────
  step "Applying MySQL primary StatefulSet..."
  kubectl apply -f "$K8S/ctfd/mysql-statefulset.yaml"

  step "Applying Redis StatefulSet..."
  kubectl apply -f "$K8S/ctfd/redis-deployment.yaml"

  step "Applying ProxySQL..."
  kubectl apply -f "$K8S/ctfd/proxysql-configmap.yaml"
  kubectl apply -f "$K8S/ctfd/proxysql-deployment.yaml"

  # ── Wait for MySQL primary before continuing ──────────────────────────────
  step "Waiting for MySQL primary to be ready (may take 2–3 min)..."
  kubectl rollout status statefulset/mysql -n "$CTFD_NAMESPACE" --timeout=300s
  ok "MySQL primary ready"

  # ── MySQL replica ─────────────────────────────────────────────────────────
  step "Applying MySQL replica StatefulSet..."
  kubectl apply -f "$K8S/ctfd/mysql-replica-statefulset.yaml"

  # ── Network policy ────────────────────────────────────────────────────────
  step "Applying CTFd network policy..."
  kubectl apply -f "$K8S/ctfd/networkpolicy.yaml"

  # ── CTFd Deployment + Ingress ─────────────────────────────────────────────
  step "Applying CTFd deployment..."
  kubectl apply -f "$K8S/ctfd/deployment.yaml"

  step "Applying CTFd ingress..."
  kubectl apply -f "$K8S/ctfd/ingress.yaml"
  kubectl apply -f "$K8S/ctfd/ingress-login-ratelimit.yaml"

  step "Applying nginx global config (rate limiting, connection hardening)..."
  kubectl apply -f "$K8S/ctfd/nginx-global-config.yaml"

  step "Applying PodDisruptionBudgets..."
  kubectl apply -f "$K8S/ctfd/pdb.yaml"

  step "Waiting for CTFd to be ready (may take 2–3 min)..."
  kubectl rollout status deployment/ctfd -n "$CTFD_NAMESPACE" --timeout=300s
  ok "CTFd ready"

  # ── RBAC ─────────────────────────────────────────────────────────────────
  step "Applying RBAC..."
  kubectl apply -f "$K8S/rbac/challenge-controller-rbac.yaml"
  kubectl apply -f "$K8S/rbac/challenge-daemon-rbac.yaml"

  # ── challenge-manifests ConfigMap (required before controller starts) ─────
  step "Creating challenge-manifests ConfigMap (required by controller)..."
  kubectl create configmap challenge-manifests \
    --from-file="$PROJECT_ROOT/challenges/manifests" \
    -n "$CTFD_NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  # ── Controller deployments ────────────────────────────────────────────────
  step "Applying controller API..."
  kubectl apply -f "$K8S/controller/api-deployment.yaml"

  step "Applying controller daemon..."
  kubectl apply -f "$K8S/controller/daemon-deployment.yaml"

  step "Applying Cilium network policy (controller → kube-apiserver)..."
  kubectl apply -f "$K8S/controller/cilium-networkpolicy.yaml" 2>/dev/null || \
    echo "  WARNING: Cilium policy not applied (may not be supported on this cluster)"

  step "Applying RBAC for controller cluster access..."
  kubectl apply -f "$K8S/controller/cluster-rbac.yaml" 2>/dev/null || \
    kubectl apply -f "$K8S/controller/rbac.yaml"

  # ── Challenge namespace network policies ──────────────────────────────────
  step "Applying challenge namespace network policies and resource limits..."
  kubectl apply -f "$K8S/network-policies/challenges-default-deny.yaml"
  kubectl apply -f "$K8S/network-policies/challenges-allow-ingress.yaml"
  kubectl apply -f "$K8S/network-policies/challenges-allow-nodeport.yaml"
  kubectl apply -f "$K8S/network-policies/challenges-allow-dns.yaml"
  kubectl apply -f "$K8S/challenges/resource-limits.yaml"

  # CTFd namespace network policies
  kubectl apply -f "$K8S/network-policies/ctfd-default-deny.yaml" 2>/dev/null || true
  kubectl apply -f "$K8S/network-policies/ctfd-allow-internal.yaml" 2>/dev/null || true
  kubectl apply -f "$K8S/network-policies/ctfd-allow-controller-egress.yaml" 2>/dev/null || true

  ok "K8s stack deployed"

  # ── tcp-services ConfigMap (required by nginx for TCP challenge proxying) ──
  step "Creating tcp-services ConfigMap in ingress-nginx..."
  kubectl create configmap tcp-services -n ingress-nginx \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  ok "tcp-services ConfigMap ready"

  # ── MySQL replication ─────────────────────────────────────────────────────
  step "Waiting for MySQL replica to be ready..."
  kubectl rollout status statefulset/mysql-replica -n "$CTFD_NAMESPACE" --timeout=300s || \
    echo "  WARNING: MySQL replica not ready yet — continuing (replication can be set up later)"

  step "Setting up MySQL GTID replication..."
  bash "$SCRIPT_DIR/setup-mysql-replication.sh" || \
    echo "  WARNING: Replication setup failed — check setup-mysql-replication.sh manually"

  # ── Wait for controller API ───────────────────────────────────────────────
  step "Waiting for controller API to be ready..."
  kubectl rollout status deployment/controller-api -n "$CTFD_NAMESPACE" --timeout=180s
  ok "Controller API ready"

fi

# Always sync controller-key secret (even on re-runs) so K8s and CTFd stay in sync
step "Syncing controller-key secret..."
kubectl create secret generic controller-key \
  --from-literal=CONTROLLER_KEY="$CONTROLLER_KEY" \
  -n "$CTFD_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
ok "controller-key secret synced"

# ============================================================================
# Phase 4: Create challenge-manifests ConfigMap
# ============================================================================
info "Phase 4/7: Creating challenge-manifests ConfigMap"

kubectl create configmap challenge-manifests \
  --from-file="$PROJECT_ROOT/challenges/manifests" \
  -n "$CTFD_NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
ok "challenge-manifests ConfigMap applied"

# ============================================================================
# Phase 5: Build & push all base challenge images + CTFd setup + challenges
# ============================================================================
info "Phase 5–7/7: Running deploy-all.sh (images → CTFd → challenges)"

# Load .ctfd.env if available (written by setup-ctfd.sh on first run)
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

export CTFD_URL
export CTF_MASTER_SECRET
export CONTROLLER_KEY
export CTFD_NAMESPACE
export CHALLENGE_NAMESPACE
export ENV_FILE
export SKIP_IMAGES
[[ -n "${TEAMS_CSV:-}" ]] && export TEAMS_CSV

# Auto-detect ingress LB IP so setup-ctfd.sh can bypass DNS (needed on fresh
# deploys before DNS propagates and while Let's Encrypt cert is being issued).
if [[ -z "${INGRESS_IP:-}" ]]; then
  INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  [[ -n "$INGRESS_IP" ]] && step "Auto-detected INGRESS_IP: $INGRESS_IP"
fi
[[ -n "${INGRESS_IP:-}" ]] && export INGRESS_IP

bash "$SCRIPT_DIR/deploy-all.sh"

# ============================================================================
# Done
# ============================================================================
echo
echo "╔══════════════════════════════════════════════════╗"
echo "║         Platform bootstrap complete!             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  CTFd:           $CTFD_URL"
echo "║  Credentials:    $ENV_FILE"
echo "║  CONTROLLER_KEY: (stored in $ENV_FILE — not shown)"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Next:                                           ║"
echo "║  1. Set event start/end at /admin/config         ║"
echo "║  2. Run: docs/pre-event-checklist.md             ║"
echo "╚══════════════════════════════════════════════════╝"
echo
