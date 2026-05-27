#!/usr/bin/env bash

set -euo pipefail

PORT="${LOKI_PORT:-3100}"
LIMIT="${LOKI_LIMIT:-50}"
DIRECTION="${LOKI_DIRECTION:-backward}"
BASE_URL="http://127.0.0.1:${PORT}/loki/api/v1/query_range"

usage() {
  cat <<'EOF'
Usage:
  scripts/live-logs.sh all
  scripts/live-logs.sh ctfd
  scripts/live-logs.sh audit
  scripts/live-logs.sh challenges [team_id]
  scripts/live-logs.sh challenge <team_id> <challenge_id>
  scripts/live-logs.sh events
  scripts/live-logs.sh flows
  scripts/live-logs.sh raw '<logql query>'

Examples:
  kubectl port-forward -n monitoring svc/loki 3100:3100
  scripts/live-logs.sh all
  scripts/live-logs.sh audit
  scripts/live-logs.sh challenges 112
  scripts/live-logs.sh challenge 112 yami-sukehiro
  scripts/live-logs.sh raw '{namespace="ctfd"} |= "\"audit_event\": true"'

Environment:
  LOKI_PORT       Local Loki port. Default: 3100
  LOKI_LIMIT      Result limit. Default: 50
  LOKI_DIRECTION  backward|forward. Default: backward
EOF
}

require_query() {
  if [[ -z "${1:-}" ]]; then
    usage
    exit 1
  fi
}

run_query() {
  local query="$1"

  curl -sG "${BASE_URL}" \
    --data-urlencode "query=${query}" \
    --data-urlencode "limit=${LIMIT}" \
    --data-urlencode "direction=${DIRECTION}"
}

mode="${1:-}"

case "${mode}" in
  all)
    query='{cluster="infodays-ctf"}'
    ;;
  ctfd)
    query='{namespace="ctfd"}'
    ;;
  audit)
    query='{namespace="ctfd"} |= "\"audit_event\": true"'
    ;;
  challenges)
    if [[ -n "${2:-}" ]]; then
      query="{namespace=\"challenges\",team=\"${2}\"}"
    else
      query='{namespace="challenges"}'
    fi
    ;;
  challenge)
    require_query "${2:-}"
    require_query "${3:-}"
    query="{namespace=\"challenges\",team=\"${2}\",challenge=\"${3}\"}"
    ;;
  events)
    query='{namespace="kube-system"} |= "\"kind\":\"kubernetes_event\""'
    ;;
  flows)
    query='{namespace="kube-system"} |= "\"verdict\":\"FORWARDED\""'
    ;;
  raw)
    require_query "${2:-}"
    query="${2}"
    ;;
  -h|--help|help|"")
    usage
    exit 0
    ;;
  *)
    echo "Unknown mode: ${mode}" >&2
    usage
    exit 1
    ;;
esac

run_query "${query}"
