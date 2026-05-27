#!/usr/bin/env bash
# Thin wrapper around generate-static-artifacts.py.
#
# Usage:
#   CTFD_URL=https://ctfd.infodays.net \
#   CTFD_ADMIN_TOKEN=... CTF_MASTER_SECRET=... \
#   bash scripts/generate-static-artifacts.sh
#
# Or with explicit flags:
#   bash scripts/generate-static-artifacts.sh \
#     --ctfd-url https://ctfd.infodays.net \
#     --admin-token "$CTFD_ADMIN_TOKEN" \
#     --master-secret "$CTF_MASTER_SECRET"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ARGS=("$@")

# Inject env vars if corresponding flags not already present
if [[ "${ARGS[*]:-}" != *"--ctfd-url"* ]]; then
  : "${CTFD_URL:?CTFD_URL must be set (or pass --ctfd-url)}"
  ARGS+=(--ctfd-url "$CTFD_URL")
fi
if [[ "${ARGS[*]:-}" != *"--admin-token"* ]]; then
  : "${CTFD_ADMIN_TOKEN:?CTFD_ADMIN_TOKEN must be set (or pass --admin-token)}"
  ARGS+=(--admin-token "$CTFD_ADMIN_TOKEN")
fi
if [[ "${ARGS[*]:-}" != *"--master-secret"* ]]; then
  : "${CTF_MASTER_SECRET:?CTF_MASTER_SECRET must be set (or pass --master-secret)}"
  ARGS+=(--master-secret "$CTF_MASTER_SECRET")
fi

exec python3 "$SCRIPT_DIR/generate-static-artifacts.py" "${ARGS[@]}"
