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

# Test 1: Attempt to deploy root pod (should be rejected)
echo "Test 1: Attempting to deploy root pod (should be rejected)..."
OUTPUT=$(kubectl run root-test --image=busybox:1.35 --restart=Never -n challenges --overrides='{"spec":{"securityContext":{"runAsUser":0}}}' -- sleep 5 2>&1 || true)

# Check for PSA rejection keywords specifically (not generic "Error" which could be a
# transient kubectl connectivity error)
if echo "$OUTPUT" | grep -qE "forbidden|violates"; then
  echo "PASS: Root pod was rejected by admission controller"
  # Clean up if it was somehow created
  kubectl delete pod root-test -n challenges --ignore-not-found >/dev/null 2>&1
else
  echo "FAIL: Root pod was not rejected"
  kubectl delete pod root-test -n challenges --ignore-not-found >/dev/null 2>&1
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 2: Deploy compliant pod (should be accepted)
echo "Test 2: Deploying compliant pod (uid=1000, should be accepted)..."
if kubectl run uid-test --image=busybox:1.35 --restart=Never -n challenges \
  --overrides='{"spec":{"securityContext":{"runAsUser":1000,"runAsNonRoot":true,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"uid-test","image":"busybox:1.35","args":["sleep","5"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' \
  >/dev/null 2>&1; then
  echo "PASS: Compliant pod was accepted"
else
  echo "FAIL: Compliant pod was rejected"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Cleanup
echo "Cleaning up test pod..."
kubectl delete pod uid-test -n challenges --ignore-not-found >/dev/null 2>&1

# Wait for pod deletion
sleep 2

rm -f "$KUBECONFIG"

echo ""
echo "✓ All PSA validation tests passed"
exit 0
