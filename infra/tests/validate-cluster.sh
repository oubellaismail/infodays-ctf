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

# Set permissions on kubeconfig
chmod 600 "$KUBECONFIG"

# Test 1: Check namespaces exist
if kubectl get namespace ctfd challenges monitoring >/dev/null 2>&1; then
  echo "PASS: All three namespaces (ctfd, challenges, monitoring) exist"
else
  echo "FAIL: Could not find all required namespaces"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 2: Check ingress-nginx is running
if kubectl get pods -n ingress-nginx 2>/dev/null | grep -q "Running"; then
  echo "PASS: Ingress-nginx controller is running"
else
  echo "FAIL: Ingress-nginx controller not running"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 3: Check DOCR pull secret in ctfd
if kubectl get secret docr-pull-secret -n ctfd >/dev/null 2>&1; then
  echo "PASS: DOCR pull secret exists in ctfd namespace"
else
  echo "FAIL: DOCR pull secret not found in ctfd namespace"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 4: Check DOCR pull secret in challenges
if kubectl get secret docr-pull-secret -n challenges >/dev/null 2>&1; then
  echo "PASS: DOCR pull secret exists in challenges namespace"
else
  echo "FAIL: DOCR pull secret not found in challenges namespace"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Cleanup
rm -f "$KUBECONFIG"

echo ""
echo "✓ All cluster validation tests passed"
exit 0
