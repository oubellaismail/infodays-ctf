#!/usr/bin/env bash
set -euo pipefail

NS="monitoring"

info() {
  echo "→ $*"
}

fail() {
  echo "✘ $*" >&2
  exit 1
}

require_secret() {
  local name="$1"
  local namespace="${2:-$NS}"

  if ! kubectl get secret "$name" -n "$namespace" >/dev/null 2>&1; then
    fail "Required secret ${namespace}/${name} is missing"
  fi
}

wait_for_rollout() {
  local kind="$1"
  local name="$2"
  local namespace="${3:-$NS}"
  kubectl rollout status "${kind}/${name}" -n "$namespace" --timeout=300s
}

query_loki_from_cluster() {
  local path="$1"
  LOKI_PATH="$path" kubectl exec -n ctfd deploy/ctfd -- python3 - <<'PY'
import os
import urllib.request

url = f"http://loki.monitoring.svc.cluster.local:3100{os.environ['LOKI_PATH']}"
with urllib.request.urlopen(url, timeout=3) as response:
    print(response.read().decode()[:1000])
PY
}

wait_for_loki_ready() {
  local attempt
  for attempt in $(seq 1 30); do
    if query_loki_from_cluster "/ready" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

query_loki_contains() {
  local query="$1"
  local seconds_back="${2:-300}"
  LOKI_QUERY="$query" SECONDS_BACK="$seconds_back" kubectl exec -n ctfd deploy/ctfd -- python3 - <<'PY'
import json
import os
import sys
import time
import urllib.parse
import urllib.request

end_ns = int(time.time() * 1_000_000_000)
start_ns = end_ns - int(os.environ["SECONDS_BACK"]) * 1_000_000_000
params = urllib.parse.urlencode({
    "query": os.environ["LOKI_QUERY"],
    "start": str(start_ns),
    "end": str(end_ns),
    "limit": "20",
})
url = f"http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/query_range?{params}"
with urllib.request.urlopen(url, timeout=5) as response:
    payload = json.load(response)

result = payload.get("data", {}).get("result", [])
if result:
    print(json.dumps(result[:2], indent=2)[:1200])
    sys.exit(0)
sys.exit(1)
PY
}

retry_query_loki_contains() {
  local query="$1"
  local seconds_back="${2:-300}"
  local timeout="${3:-120}"
  local waited=0

  while (( waited < timeout )); do
    if query_loki_contains "$query" "$seconds_back" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
    waited=$((waited + 5))
  done

  return 1
}

emit_pod_log_marker() {
  local marker="$1"
  kubectl exec -n ctfd deploy/ctfd -- sh -lc "echo ${marker} > /proc/1/fd/1"
}

emit_event_marker() {
  local marker="$1"
  local event_name="logging-smoke-$(date +%s)"
  local timestamp
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Event
metadata:
  name: ${event_name}
  namespace: ${NS}
type: Normal
reason: LoggingSmokeTest
message: ${marker}
reportingComponent: deploy-logging.sh
reportingInstance: $(hostname)
involvedObject:
  apiVersion: v1
  kind: Pod
  name: loki-0
  namespace: ${NS}
source:
  component: deploy-logging.sh
firstTimestamp: ${timestamp}
lastTimestamp: ${timestamp}
count: 1
EOF
}

emit_flow_marker() {
  kubectl exec -n ctfd deploy/ctfd -- python3 - <<'PY'
import urllib.request

try:
    with urllib.request.urlopen("http://loki.monitoring.svc.cluster.local:3100/ready", timeout=3) as response:
        response.read()
except Exception:
    pass
PY
}

info "Deploying Loki..."
kubectl apply -f k8s/monitoring/loki.yaml

info "Applying monitoring network policies..."
kubectl apply -f k8s/monitoring/networkpolicy.yaml

info "Checking required secrets..."
require_secret grafana-cloud-logs

info "Deploying exporters and collectors..."
kubectl apply -f k8s/monitoring/event-exporter.yaml
kubectl apply -f k8s/monitoring/hubble-flows.yaml
kubectl apply -f k8s/monitoring/alloy-node.yaml
kubectl rollout restart daemonset/alloy-node -n "$NS" >/dev/null
kubectl rollout restart deployment/kubernetes-event-exporter -n kube-system >/dev/null
kubectl rollout restart deployment/hubble-flow-exporter -n kube-system >/dev/null
kubectl delete deployment alloy-cluster -n "$NS" --ignore-not-found >/dev/null

info "Waiting for Loki..."
wait_for_rollout statefulset loki

info "Waiting for node collector..."
wait_for_rollout daemonset alloy-node

info "Waiting for Kubernetes event exporter..."
wait_for_rollout deployment kubernetes-event-exporter kube-system

info "Waiting for Hubble flow exporter..."
wait_for_rollout deployment hubble-flow-exporter kube-system

info "Verifying Loki readiness..."
wait_for_loki_ready || fail "Loki did not become queryable from inside the cluster"

info "Smoke testing pod log ingestion..."
APP_MARKER="CODEX_LOG_SMOKE_$(date +%s)"
emit_pod_log_marker "$APP_MARKER"
retry_query_loki_contains "{cluster=\"infodays-ctf\"} |= \"${APP_MARKER}\"" 300 120 || \
  fail "Synthetic pod log marker did not appear in Loki"

info "Smoke testing Kubernetes event ingestion..."
EVENT_MARKER="CODEX_EVENT_SMOKE_$(date +%s)"
emit_event_marker "$EVENT_MARKER"
retry_query_loki_contains "{namespace=\"kube-system\",container=\"event-exporter\"} |= \"${EVENT_MARKER}\"" 300 120 || \
  fail "Synthetic Kubernetes event marker did not appear in Loki"

info "Smoke testing Hubble flow ingestion..."
emit_flow_marker
retry_query_loki_contains "{namespace=\"kube-system\",container=\"hubble\"} |= \"\\\"namespace\\\":\\\"ctfd\\\"\" |= \"\\\"destination_port\\\":3100\"" 300 120 || \
  fail "Synthetic Hubble flow marker did not appear in Loki"

info "Best-effort check for node syslog stream..."
if retry_query_loki_contains "{job=\"node/syslog\"}" 900 30; then
  echo "✓ Node syslog stream is present"
else
  echo "⚠ Node syslog stream not observed during smoke test window"
fi

echo "✓ Logging stack deployed and verified"
