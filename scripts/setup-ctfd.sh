#!/bin/bash
set -euo pipefail

# setup-ctfd.sh - Idempotent CTFd configuration script
# Waits for CTFd readiness, then configures event settings via API

# Environment variables (required)
CTFD_URL="${CTFD_URL:-}"
CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:-}"

# Environment variables (optional)
CTFD_EVENT_NAME="${CTFD_EVENT_NAME:-InfoDays CTF}"
CTFD_FLAG_FORMAT="${CTFD_FLAG_FORMAT:-infodays{...}}"
CTFD_START_TIME="${CTFD_START_TIME:-}"
CTFD_END_TIME="${CTFD_END_TIME:-}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_TIMEOUT="${POLL_TIMEOUT:-300}"

# Validation
if [[ -z "$CTFD_URL" ]]; then
  echo "ERROR: CTFD_URL environment variable not set" >&2
  exit 2
fi

if [[ -z "$CTFD_ADMIN_TOKEN" ]]; then
  echo "ERROR: CTFD_ADMIN_TOKEN environment variable not set" >&2
  exit 2
fi

# Wait for CTFd readiness
echo "Waiting for CTFd at $CTFD_URL/healthcheck..."
ATTEMPT=0
MAX_ATTEMPTS=$(( POLL_TIMEOUT / POLL_INTERVAL ))
READY=0
while [[ $ATTEMPT -lt $MAX_ATTEMPTS ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  if curl -s -o /dev/null -w "%{http_code}" "$CTFD_URL/healthcheck" | grep -q "200"; then
    echo "CTFd ready (attempt ${ATTEMPT}/${MAX_ATTEMPTS})."
    READY=1
    break
  fi
  sleep "$POLL_INTERVAL"
done

if [[ $READY -eq 0 ]]; then
  echo "ERROR: CTFd not ready after ${POLL_TIMEOUT}s timeout" >&2
  exit 1
fi

# Configure CTFd event name via API
echo "Configuring event name: \"$CTFD_EVENT_NAME\"..."
RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/ctfd_response.json \
  -X PATCH \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"ctf_name\": \"$CTFD_EVENT_NAME\"}" \
  "$CTFD_URL/api/v1/configs")
if [[ ! "$RESPONSE" =~ ^20[0-9]$ ]]; then
  echo "ERROR: Failed to set event name (HTTP $RESPONSE)" >&2; cat /tmp/ctfd_response.json >&2; rm -f /tmp/ctfd_response.json; exit 2
fi
echo "Configuring event name: \"$CTFD_EVENT_NAME\"... OK"

# Configure team mode
echo "Configuring team mode: on..."
RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/ctfd_response.json \
  -X PATCH \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"team_mode": "teams"}' \
  "$CTFD_URL/api/v1/configs")
if [[ ! "$RESPONSE" =~ ^20[0-9]$ ]]; then
  echo "ERROR: Failed to set team mode (HTTP $RESPONSE)" >&2; cat /tmp/ctfd_response.json >&2; rm -f /tmp/ctfd_response.json; exit 2
fi
echo "Configuring team mode: on... OK"

# Configure registration
echo "Configuring registration: disabled..."
RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/ctfd_response.json \
  -X PATCH \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"registration_visibility": "private"}' \
  "$CTFD_URL/api/v1/configs")
if [[ ! "$RESPONSE" =~ ^20[0-9]$ ]]; then
  echo "ERROR: Failed to set registration visibility (HTTP $RESPONSE)" >&2; cat /tmp/ctfd_response.json >&2; rm -f /tmp/ctfd_response.json; exit 2
fi
echo "Configuring registration: disabled... OK"

rm -f /tmp/ctfd_response.json
echo "Setup complete."
exit 0
