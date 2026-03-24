#!/bin/bash
# Master validation script — runs all validation tests in sequence

set -e

echo "========================================="
echo "InfoDays CTF — Full Validation Suite"
echo "========================================="
echo ""

FAILED=0

# Test 1: Cluster validation
echo "Running cluster validation..."
if bash infra/tests/validate-cluster.sh; then
  echo "✓ Cluster validation passed"
else
  echo "✗ Cluster validation failed"
  FAILED=$((FAILED + 1))
fi

echo ""

# Test 2: TLS validation
echo "Running TLS validation..."
if bash infra/tests/validate-tls.sh; then
  echo "✓ TLS validation passed"
else
  echo "✗ TLS validation failed"
  FAILED=$((FAILED + 1))
fi

echo ""

# Test 3: Network isolation validation
echo "Running network isolation validation..."
if bash infra/tests/validate-network-isolation.sh; then
  echo "✓ Network isolation validation passed"
else
  echo "✗ Network isolation validation failed"
  FAILED=$((FAILED + 1))
fi

echo ""

# Test 4: Pod security standards validation
echo "Running PSA validation..."
if bash infra/tests/validate-psa.sh; then
  echo "✓ PSA validation passed"
else
  echo "✗ PSA validation failed"
  FAILED=$((FAILED + 1))
fi

echo ""
echo "========================================="

if [ $FAILED -eq 0 ]; then
  echo "✓ ALL VALIDATIONS PASSED"
  echo "========================================="
  exit 0
else
  echo "✗ $FAILED VALIDATION(S) FAILED"
  echo "========================================="
  exit 1
fi
