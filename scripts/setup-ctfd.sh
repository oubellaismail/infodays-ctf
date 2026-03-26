#!/bin/bash
set -euo pipefail

# setup-ctfd.sh — Fully idempotent CTFd bootstrap + team import.
#
# Handles TWO scenarios:
#   1. Fresh CTFd (/setup → 200) → creates admin + token via Python ORM,
#      saves credentials to ENV_FILE, restarts pods, then applies config.
#   2. Already-configured CTFd (/setup → 302) → loads token from ENV_FILE,
#      validates it, and applies config (idempotent).
#
# After setup, if TEAMS_CSV is set, teams are imported automatically.
#
# Usage (fresh deploy):
#   CTFD_URL=https://ctfd.infodays.net bash scripts/setup-ctfd.sh
#
# Usage (re-run / already configured):
#   CTFD_URL=https://ctfd.infodays.net bash scripts/setup-ctfd.sh
#   (token auto-loaded from .ctfd.env)
#
# Usage (with team import):
#   CTFD_URL=https://ctfd.infodays.net TEAMS_CSV=data/teams.csv bash scripts/setup-ctfd.sh
#
# Required:
#   CTFD_URL          — e.g. https://ctfd.infodays.net
#
# Optional (with defaults):
#   CTFD_ADMIN_NAME     — admin display name        (default: admin)
#   CTFD_ADMIN_EMAIL    — admin email                (default: admin@infodays.net)
#   CTFD_ADMIN_PASSWORD — admin password             (default: auto-generated)
#   CTFD_EVENT_NAME     — CTF event name             (default: InfoDays CTF)
#   CTFD_NAMESPACE      — K8s namespace for CTFd     (default: ctfd)
#   TEAMS_CSV           — path to teams CSV file     (default: empty, skips import)
#   ENV_FILE            — credentials file path      (default: .ctfd.env)
#   INGRESS_IP          — LB IP to bypass DNS        (optional)
#   POLL_INTERVAL       — readiness poll interval    (default: 5s)
#   POLL_TIMEOUT        — readiness poll timeout     (default: 300s)

# ---------------------------------------------------------------------------
# Step 0: Operational params from env/defaults (command-line wins for these)
# ---------------------------------------------------------------------------
CTFD_URL="${CTFD_URL:-}"
CTFD_ADMIN_NAME="${CTFD_ADMIN_NAME:-admin}"
CTFD_ADMIN_EMAIL="${CTFD_ADMIN_EMAIL:-admin@infodays.net}"
CTFD_ADMIN_PASSWORD="${CTFD_ADMIN_PASSWORD:-}"
CTFD_EVENT_NAME="${CTFD_EVENT_NAME:-InfoDays CTF}"
CTFD_NAMESPACE="${CTFD_NAMESPACE:-ctfd}"
TEAMS_CSV="${TEAMS_CSV:-}"
INGRESS_IP="${INGRESS_IP:-}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_TIMEOUT="${POLL_TIMEOUT:-300}"
ENV_FILE="${ENV_FILE:-.ctfd.env}"

# Credentials (token/password) come from ENV_FILE — it always wins over the
# shell environment, ensuring stale exports from previous deploys don't interfere.
# Operational params above are NOT stored in ENV_FILE so they remain overridable.
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  echo "INFO: Loaded credentials from $ENV_FILE"
fi

# If token still not set after file load, fall back to shell env
CTFD_ADMIN_TOKEN="${CTFD_ADMIN_TOKEN:-}"

if [[ -z "$CTFD_URL" ]]; then
  echo "ERROR: CTFD_URL is not set." >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# DNS bypass: if INGRESS_IP is set, route requests directly to the LB IP.
# Useful on fresh deploys before DNS propagates.
# ---------------------------------------------------------------------------
CURL_RESOLVE_OPTS=()
if [[ -n "$INGRESS_IP" ]]; then
  CTFD_HOST="${CTFD_URL#http://}"; CTFD_HOST="${CTFD_HOST#https://}"; CTFD_HOST="${CTFD_HOST%%/*}"
  CURL_RESOLVE_OPTS+=(--resolve "${CTFD_HOST}:80:${INGRESS_IP}")
  CURL_RESOLVE_OPTS+=(--resolve "${CTFD_HOST}:443:${INGRESS_IP}")
  echo "INFO: DNS bypass active — routing $CTFD_HOST → $INGRESS_IP"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RESP_TMP=$(mktemp /tmp/ctfd_resp_XXXXXX)
trap 'rm -f "$RESP_TMP"' EXIT

ctfd_api() {
  local method="$1" endpoint="$2" data="${3:-}"
  local args=(-s -w "%{http_code}" -o "$RESP_TMP"
    "${CURL_RESOLVE_OPTS[@]+"${CURL_RESOLVE_OPTS[@]}"}"
    -X "$method"
    -H "Authorization: Token $CTFD_ADMIN_TOKEN"
    -H "Content-Type: application/json")
  [[ -n "$data" ]] && args+=(-d "$data")
  curl "${args[@]}" "${CTFD_URL}${endpoint}"
}

wait_for_ctfd() {
  local label="${1:-CTFd}"
  local attempt=0 max_attempts=$(( POLL_TIMEOUT / POLL_INTERVAL ))
  echo "Waiting for $label ..."
  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    local http
    http=$(curl -s -o /dev/null -w "%{http_code}" \
      "${CURL_RESOLVE_OPTS[@]+"${CURL_RESOLVE_OPTS[@]}"}" \
      "$CTFD_URL/healthcheck" || true)
    if [[ "$http" == "200" ]]; then
      echo "$label ready (attempt ${attempt}/${max_attempts})."
      return 0
    fi
    sleep "$POLL_INTERVAL"
  done
  echo "ERROR: $label not ready after ${POLL_TIMEOUT}s." >&2
  return 1
}

save_env_file() {
  local tmp
  tmp=$(mktemp /tmp/ctfd_env_XXXXXX)
  cat > "$tmp" <<EOF
# CTFd credentials — written by setup-ctfd.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Sourced automatically on every run of setup-ctfd.sh and import-teams.py.
# Do NOT add CTFD_URL here — pass it as an env var so it stays overridable.
export CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN"
export CTFD_ADMIN_NAME="$CTFD_ADMIN_NAME"
export CTFD_ADMIN_EMAIL="$CTFD_ADMIN_EMAIL"
export CTFD_ADMIN_PASSWORD="$CTFD_ADMIN_PASSWORD"
EOF
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
  echo "INFO: Credentials saved to $ENV_FILE (mode 600)"
}

apply_config() {
  local label="$1" payload="$2"
  echo "Configuring $label..."
  local resp
  resp=$(ctfd_api PATCH /api/v1/configs "$payload")
  if [[ ! "$resp" =~ ^20[0-9]$ ]]; then
    echo "ERROR: Failed to configure $label (HTTP $resp)." >&2
    cat "$RESP_TMP" >&2
    exit 2
  fi
  echo "Configuring $label... OK"
}

# ---------------------------------------------------------------------------
# Step 1: Wait for CTFd to be reachable
# ---------------------------------------------------------------------------
wait_for_ctfd "CTFd"

# ---------------------------------------------------------------------------
# Step 2: Detect fresh install vs already configured
# ---------------------------------------------------------------------------
SETUP_HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  "${CURL_RESOLVE_OPTS[@]+"${CURL_RESOLVE_OPTS[@]}"}" "$CTFD_URL/setup")

if [[ "$SETUP_HTTP" == "200" ]]; then
  echo ""
  echo "=== Fresh CTFd detected — running initial setup ==="
  echo ""

  if [[ -z "$CTFD_ADMIN_PASSWORD" ]]; then
    CTFD_ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
    echo "INFO: Generated admin password: $CTFD_ADMIN_PASSWORD"
  fi

  CTFD_POD=$(kubectl -n "$CTFD_NAMESPACE" get pods -l app=ctfd \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -z "$CTFD_POD" ]]; then
    echo "ERROR: No CTFd pod found in namespace '$CTFD_NAMESPACE'." >&2
    exit 1
  fi
  echo "Using pod: $CTFD_POD"

  # All values injected via env (not string-interpolated) to safely handle
  # special characters in passwords, names, and email addresses.
  SETUP_OUTPUT=$(
    kubectl -n "$CTFD_NAMESPACE" exec "$CTFD_POD" \
      -- env \
        "SETUP_ADMIN_NAME=$CTFD_ADMIN_NAME" \
        "SETUP_ADMIN_EMAIL=$CTFD_ADMIN_EMAIL" \
        "SETUP_ADMIN_PASSWORD=$CTFD_ADMIN_PASSWORD" \
        "SETUP_EVENT_NAME=$CTFD_EVENT_NAME" \
      python3 -c '
import sys, os, secrets, datetime
sys.path.insert(0, "/opt/CTFd")
os.chdir("/opt/CTFd")

from CTFd import create_app
from CTFd.utils.crypto import hash_password
from CTFd.models import db

admin_name     = os.environ["SETUP_ADMIN_NAME"]
admin_email    = os.environ["SETUP_ADMIN_EMAIL"]
admin_password = os.environ["SETUP_ADMIN_PASSWORD"]
event_name     = os.environ["SETUP_EVENT_NAME"]

app = create_app()
with app.app_context():
    user_count = db.session.execute(db.text("SELECT COUNT(*) FROM users")).scalar()
    if user_count > 0:
        print("ALREADY_SETUP")
        sys.exit(0)

    pw_hash = hash_password(admin_password)
    db.session.execute(db.text(
        "INSERT INTO users (name, email, password, type, verified, hidden, banned) "
        "VALUES (:n, :e, :p, :t, :v, :h, :b)"
    ), {"n": admin_name, "e": admin_email,
        "p": pw_hash, "t": "admin", "v": 1, "h": 0, "b": 0})
    db.session.flush()

    uid = db.session.execute(
        db.text("SELECT id FROM users WHERE email=:e"), {"e": admin_email}
    ).scalar()

    for k, val in [
        ("ctf_name",                event_name),
        ("user_mode",               "teams"),
        ("registration_visibility", "private"),
        ("setup",                   "True"),
    ]:
        db.session.execute(db.text(
            "INSERT INTO config (`key`, value) VALUES (:k, :v) "
            "ON DUPLICATE KEY UPDATE value = :v"
        ), {"k": k, "v": val})

    expiry = datetime.datetime.utcnow() + datetime.timedelta(days=365)
    token_value = "ctfd_" + secrets.token_hex(32)
    db.session.execute(db.text(
        "INSERT INTO tokens (type, user_id, created, expiration, value, description) "
        "VALUES (:t, :uid, :c, :e, :v, :d)"
    ), {"t": "user", "uid": uid,
        "c": datetime.datetime.utcnow(),
        "e": expiry,
        "v": token_value, "d": "setup-ctfd-auto"})

    db.session.commit()

    # Flush Redis memoize cache so new pods read fresh config from MySQL.
    from CTFd.cache import cache
    cache.clear()

    print("TOKEN=" + token_value)
' 2>&1 | grep -E '^TOKEN=|^ALREADY_SETUP' || true
  )

  if [[ "$SETUP_OUTPUT" == "ALREADY_SETUP" ]]; then
    echo "Admin user already exists (partial previous setup)."
    if [[ -z "$CTFD_ADMIN_TOKEN" ]]; then
      echo "ERROR: No token available. Either:" >&2
      echo "  - Re-run with CTFD_ADMIN_TOKEN=<token>" >&2
      echo "  - Or wipe the CTFd database and start fresh." >&2
      exit 2
    fi
    echo "INFO: Using token from $ENV_FILE"

  elif [[ "$SETUP_OUTPUT" == TOKEN=* ]]; then
    CTFD_ADMIN_TOKEN="${SETUP_OUTPUT#TOKEN=}"

    echo ""
    echo "  Admin:    $CTFD_ADMIN_NAME <$CTFD_ADMIN_EMAIL>"
    echo "  Password: $CTFD_ADMIN_PASSWORD"
    echo "  Token:    $CTFD_ADMIN_TOKEN"
    echo ""

    save_env_file

    # Pods that were running before the ORM insert have a stale in-memory config
    # cache and still redirect API calls to /setup. Rolling restart clears it.
    echo "Restarting CTFd to flush config cache..."
    kubectl rollout restart deployment/ctfd -n "$CTFD_NAMESPACE"
    kubectl rollout status deployment/ctfd -n "$CTFD_NAMESPACE" --timeout=180s
    echo "CTFd restarted."
    echo ""

    wait_for_ctfd "CTFd (post-restart)"

  else
    echo "ERROR: Unexpected output from setup script: '$SETUP_OUTPUT'" >&2
    echo "  Check that the CTFd pod is healthy and the Python path is correct." >&2
    exit 1
  fi

else
  echo "CTFd already configured (HTTP $SETUP_HTTP on /setup)."

  if [[ -z "$CTFD_ADMIN_TOKEN" ]]; then
    echo "ERROR: No admin token available." >&2
    echo "  Run: CTFD_ADMIN_TOKEN=<token> $0" >&2
    echo "  Or place credentials in $ENV_FILE" >&2
    exit 2
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: Validate token
# ---------------------------------------------------------------------------
echo "Validating admin token..."
TOKEN_CHECK=$(ctfd_api GET /api/v1/users/me)
if [[ "$TOKEN_CHECK" != "200" ]]; then
  echo "ERROR: Admin token is invalid (HTTP $TOKEN_CHECK)." >&2
  cat "$RESP_TMP" >&2
  exit 2
fi
echo "Validating admin token... OK"

# ---------------------------------------------------------------------------
# Step 4: Apply configuration (idempotent)
# ---------------------------------------------------------------------------
apply_config "event name"   "{\"ctf_name\": \"$CTFD_EVENT_NAME\"}"
apply_config "team mode"    '{"user_mode": "teams"}'
apply_config "registration" '{"registration_visibility": "private"}'

# ---------------------------------------------------------------------------
# Step 5: Import teams (optional — only if TEAMS_CSV is set)
# ---------------------------------------------------------------------------
if [[ -n "$TEAMS_CSV" ]]; then
  if [[ ! -f "$TEAMS_CSV" ]]; then
    echo "ERROR: TEAMS_CSV='$TEAMS_CSV' not found." >&2
    exit 2
  fi
  echo ""
  echo "=== Importing teams from $TEAMS_CSV ==="
  CTFD_URL="$CTFD_URL" CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
    python3 scripts/import-teams.py "$TEAMS_CSV"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "Setup complete."
echo "  URL:   $CTFD_URL"
echo "  Token: $CTFD_ADMIN_TOKEN"
echo "  Creds: $ENV_FILE"
exit 0
