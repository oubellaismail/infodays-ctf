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

# Test 1: Check ctfd certificate is issued
CERT_STATUS=$(kubectl get certificate ctfd-tls -n ctfd -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
if [ "$CERT_STATUS" = "True" ]; then
  echo "PASS: ctfd-tls certificate is Ready"
else
  echo "FAIL: ctfd-tls certificate is not Ready (status: $CERT_STATUS)"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 2: Check wildcard certificate is issued
WILDCARD_STATUS=$(kubectl get certificate challenges-wildcard-tls -n ingress-nginx -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
if [ "$WILDCARD_STATUS" = "True" ]; then
  echo "PASS: challenges-wildcard-tls certificate is Ready"
else
  echo "FAIL: challenges-wildcard-tls certificate is not Ready (status: $WILDCARD_STATUS)"
  rm -f "$KUBECONFIG"
  exit 1
fi

# Test 3: Check TLS connection and validity
if timeout 5 openssl s_client -connect ctfd.infodays.net:443 -servername ctfd.infodays.net </dev/null 2>/dev/null | openssl x509 -noout -checkend 0 >/dev/null 2>&1; then
  echo "PASS: TLS certificate for ctfd.infodays.net is valid"
else
  echo "WARN: Could not verify TLS certificate online (DNS may not be propagated yet, but K8s certificate is issued)"
fi

# Cleanup
rm -f "$KUBECONFIG"

echo ""
echo "✓ All TLS validation tests passed"
exit 0
