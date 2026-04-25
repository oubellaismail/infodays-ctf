#!/usr/bin/env bash
set -euo pipefail

# backup-mysql.sh — Back up the CTFd MySQL database to a local SQL file.
#
# Fetches the MySQL root password from K8s Secret ctfd-secrets,
# runs mysqldump inside the MySQL pod, and saves the result to backups/
#
# Usage:
#   bash scripts/backup-mysql.sh
#
# Output:
#   backups/ctfd-backup-YYYY-MM-DD_HH-MM-SS.sql
#
# Exit codes:
#   0 — backup succeeded
#   1 — MySQL pod not found or not ready
#   2 — mysqldump failed
#   3 — failed to read MYSQL_ROOT_PASSWORD from K8s Secret

# Determine repository root (fall back to script's parent directory if not in a git repo)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
BACKUP_DIR="${REPO_ROOT}/backups"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
OUTPUT_FILE="${BACKUP_DIR}/ctfd-backup-${TIMESTAMP}.sql"
STDERR_FILE=$(mktemp "${TMPDIR:-/tmp}/mysqldump-stderr.XXXXXX")
trap 'rm -f "$STDERR_FILE"' EXIT

mkdir -p "${BACKUP_DIR}"

base64_decode() {
  if base64 --decode >/dev/null 2>&1 <<<""; then
    base64 --decode
  else
    base64 -D
  fi
}

# Fetch MySQL root password from K8s Secret ctfd-secrets
echo "Fetching MySQL root password from K8s Secret ctfd-secrets..."
MYSQL_ROOT_PASSWORD=$(kubectl get secret ctfd-secrets -n ctfd \
  -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' 2>/dev/null | base64_decode) || {
  echo "ERROR: Failed to read MYSQL_ROOT_PASSWORD from K8s Secret ctfd-secrets in namespace ctfd." >&2
  echo "Ensure kubectl is configured and the secret exists." >&2
  exit 3
}

# Verify MySQL pod is running
echo "Checking MySQL pod status..."
MYSQL_POD=$(kubectl get pod -n ctfd -l app=mysql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || {
  echo "ERROR: No MySQL pod found in namespace ctfd (label app=mysql)." >&2
  exit 1
}

if [[ -z "${MYSQL_POD}" ]]; then
  echo "ERROR: No MySQL pod found in namespace ctfd (label app=mysql)." >&2
  exit 1
fi

POD_PHASE=$(kubectl get pod "${MYSQL_POD}" -n ctfd -o jsonpath='{.status.phase}')
if [[ "${POD_PHASE}" != "Running" ]]; then
  echo "ERROR: MySQL pod ${MYSQL_POD} is not Running (phase: ${POD_PHASE})." >&2
  exit 1
fi

# Run mysqldump via kubectl exec
echo "Running mysqldump on pod ${MYSQL_POD} → ${OUTPUT_FILE}"
kubectl exec "${MYSQL_POD}" -n ctfd -- \
  mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" --single-transaction ctfd \
  > "${OUTPUT_FILE}" 2>"${STDERR_FILE}" || {
  echo "ERROR: mysqldump failed." >&2
  cat "${STDERR_FILE}" >&2
  rm -f "${OUTPUT_FILE}"
  exit 2
}

# Verify output
FILESIZE=$(wc -c < "${OUTPUT_FILE}")
if [[ "${FILESIZE}" -lt 100 ]]; then
  echo "ERROR: Backup file is suspiciously small (${FILESIZE} bytes). Check mysqldump output." >&2
  exit 2
fi

echo "✓ Backup complete: ${OUTPUT_FILE} (${FILESIZE} bytes)"
exit 0
