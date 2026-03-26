#!/usr/bin/env bash
set -uo pipefail
# Note: -e is intentionally omitted — arithmetic like ((FAILED++)) returns
# exit code 1 when transitioning from 0→1, which would abort the script.

NAMESPACE="challenges"
TESTS=(
  "tests/network-isolation/test-deny-ctfd.yaml"
  "tests/network-isolation/test-deny-cross-team.yaml"
  "tests/network-isolation/test-deny-kube-api.yaml"
  "tests/network-isolation/test-deny-metadata.yaml"
)

POD_NAMES=(
  "test-deny-ctfd"
  "test-deny-cross-team"
  "test-deny-kube-api"
  "test-deny-metadata"
)

PASSED=0
FAILED=0

# Pre-flight checks
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
  echo "ERROR: Namespace '$NAMESPACE' does not exist"
  exit 1
fi

# Helper function to wait for pod completion
wait_for_pod_completion() {
  local pod_name=$1
  local max_wait=30
  local elapsed=0

  while [ $elapsed -lt $max_wait ]; do
    phase=$(kubectl get pod "$pod_name" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")

    if [[ "$phase" == "Succeeded" ]] || [[ "$phase" == "Failed" ]]; then
      return 0
    fi

    sleep 2
    elapsed=$((elapsed + 2))
  done

  return 1
}

# Helper function to get pod exit code
get_pod_exit_code() {
  local pod_name=$1
  kubectl get pod "$pod_name" -n "$NAMESPACE" \
    -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}' 2>/dev/null || echo "999"
}

# Run all tests
for i in "${!TESTS[@]}"; do
  test_file="${TESTS[$i]}"
  pod_name="${POD_NAMES[$i]}"

  # Verify test file exists
  if [ ! -f "$test_file" ]; then
    echo "[ERROR] $pod_name — test manifest not found: $test_file"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Clean up any leftover pod from a prior run
  kubectl delete pod "$pod_name" -n "$NAMESPACE" --ignore-not-found > /dev/null 2>&1

  # Apply the test pod
  if ! kubectl apply -f "$test_file" 2>&1 | grep -v "^$"; then
    echo "[ERROR] $pod_name — failed to apply test pod manifest"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Wait for completion
  if wait_for_pod_completion "$pod_name"; then
    exit_code=$(get_pod_exit_code "$pod_name")

    # Non-zero exit = connection blocked = PASS
    if [[ "$exit_code" != "0" ]]; then
      echo "[PASS] $pod_name — connection blocked"
      PASSED=$((PASSED + 1))
    else
      echo "[FAIL] $pod_name — connection NOT blocked (exit code: $exit_code)"
      FAILED=$((FAILED + 1))
    fi
  else
    echo "[ERROR] $pod_name — pod did not complete within 30 seconds"
    FAILED=$((FAILED + 1))
  fi

  # Always cleanup
  kubectl delete pod "$pod_name" -n "$NAMESPACE" --ignore-not-found > /dev/null 2>&1
done

# Print summary
total=$((PASSED + FAILED))
echo ""
echo "$PASSED/$total isolation tests passed"

# Exit with proper code
if [ $FAILED -eq 0 ]; then
  exit 0
else
  exit 1
fi
