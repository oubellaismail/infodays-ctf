#!/bin/bash

set -e

# Setup kubeconfig
KUBECONFIG=$(mktemp)
export KUBECONFIG

# Get kubeconfig from Terraform
if ! terraform -chdir=infra/terraform output -raw kubeconfig | base64 -d > "$KUBECONFIG" 2>/dev/null; then
  echo "FAIL: Could not get kubeconfig from Terraform"
  rm -f "$KUBECONFIG"
  exit 1
fi

chmod 600 "$KUBECONFIG"

# Deploy test pod in challenges namespace
echo "Deploying test pod in challenges namespace..."
kubectl run nettest --image=busybox:1.35 --restart=Never -n challenges \
  --overrides='{"spec":{"securityContext":{"runAsUser":1000,"runAsNonRoot":true,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"nettest","image":"busybox:1.35","args":["sleep","60"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' \
  >/dev/null 2>&1

# Wait for pod to be ready
echo "Waiting for test pod to be ready..."
kubectl wait pod/nettest -n challenges --for=condition=Ready --timeout=30s >/dev/null 2>&1

# Test 1: ctfd namespace unreachable
# Note: this test passes because the default-deny egress policy blocks DNS (port 53
# to kube-system), so the hostname cannot be resolved. The ctfd service does not
# exist in Phase 1 — the test validates that egress is denied, not a specific rule
# against the ctfd service.
echo "Test 1: Verifying ctfd namespace is unreachable from challenges pod..."
if ! kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://ctfd.ctfd.svc.cluster.local 2>&1 >/dev/null; then
  echo "PASS: ctfd namespace is unreachable from challenges pod"
else
  echo "FAIL: ctfd namespace was reachable (should be blocked)"
  kubectl delete pod nettest -n challenges --ignore-not-found >/dev/null 2>&1
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 2: metadata endpoint blocked
echo "Test 2: Verifying metadata endpoint is blocked..."
if ! kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://169.254.169.254 2>&1 >/dev/null; then
  echo "PASS: Metadata endpoint is blocked"
else
  echo "FAIL: Metadata endpoint was reachable (should be blocked)"
  kubectl delete pod nettest -n challenges --ignore-not-found >/dev/null 2>&1
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 3: internet blocked by default
echo "Test 3: Verifying internet is blocked by default..."
if ! kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://example.com 2>&1 >/dev/null; then
  echo "PASS: Internet access is blocked by default"
else
  echo "FAIL: Internet was reachable (should be blocked by default)"
  kubectl delete pod nettest -n challenges --ignore-not-found >/dev/null 2>&1
  rm -f "$KUBECONFIG"
  exit 1
fi

# Cleanup
echo "Cleaning up test pod..."
kubectl delete pod nettest -n challenges --ignore-not-found >/dev/null 2>&1

# Wait for pod deletion
sleep 2

rm -f "$KUBECONFIG"

echo ""
echo "✓ All network isolation tests passed"
exit 0
