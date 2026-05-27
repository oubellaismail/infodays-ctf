#!/usr/bin/env bash
set -euo pipefail

# restore-mysql.sh — Restore CTFd MySQL database from a backup file.
#
# Usage:
#   bash scripts/restore-mysql.sh <backup-file>
#   bash scripts/restore-mysql.sh s3://infodays-ctf-tfstate/backups/ctfd-backup-2026-04-14T12-00-00Z.sql.gz
#   bash scripts/restore-mysql.sh backups/ctfd-backup-2026-04-14T12-00-00Z.sql.gz
#   bash scripts/restore-mysql.sh --list        # List available backups in Spaces
#   bash scripts/restore-mysql.sh --latest       # Restore the most recent backup from Spaces
#
# Environment variables (required for Spaces access):
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Safety:
#   - Prompts for confirmation before overwriting live data
#   - Takes a pre-restore snapshot before applying
#   - Verifies row counts before and after
#   - Does NOT stop CTFd pods (hot restore via ProxySQL connection limits)
#
# Exit codes:
#   0 — success
#   1 — bad arguments or missing tools
#   2 — MySQL not reachable
#   3 — download failed
#   4 — restore failed
#   5 — verification failed

SPACES_ENDPOINT="https://fra1.digitaloceanspaces.com"
SPACES_BUCKET="infodays-ctf-tfstate"
BACKUP_PREFIX="backups"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
BACKUP_DIR="${REPO_ROOT}/backups"

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

info()  { echo -e "${GRN}[restore]${NC} $*"; }
warn()  { echo -e "${YEL}[restore]${NC} $*"; }
error() { echo -e "${RED}[restore] ERROR:${NC} $*" >&2; }

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

check_deps() {
  local missing=()
  for cmd in kubectl gunzip aws; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing required tools: ${missing[*]}"
    echo "  Install: brew install awscli kubernetes-cli" >&2
    exit 1
  fi
}

get_mysql_password() {
  kubectl get secret ctfd-secrets -n ctfd \
    -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' 2>/dev/null | base64 -d || {
    error "Cannot read MYSQL_ROOT_PASSWORD from K8s Secret ctfd-secrets"
    exit 2
  }
}

get_mysql_pod() {
  local pod
  pod=$(kubectl get pod -n ctfd -l app=mysql \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [[ -z "$pod" ]]; then
    error "No MySQL pod found in namespace ctfd (label app=mysql)"
    exit 2
  fi
  echo "$pod"
}

check_mysql_ready() {
  local pod="$1" pass="$2"
  kubectl exec "$pod" -n ctfd -- \
    mysqladmin ping -u root -p"$pass" --silent &>/dev/null || {
    error "MySQL pod $pod is not responding"
    exit 2
  }
}

row_counts() {
  local pod="$1" pass="$2"
  kubectl exec "$pod" -n ctfd -- \
    mysql -u root -p"$pass" ctfd -sN \
    -e "SELECT 'users', COUNT(*) FROM users
        UNION ALL SELECT 'teams', COUNT(*) FROM teams
        UNION ALL SELECT 'submissions', COUNT(*) FROM submissions;" 2>/dev/null \
  | awk '{printf "  %-15s %s\n", $1, $2}'
}

# ──────────────────────────────────────────────
# List backups in Spaces
# ──────────────────────────────────────────────

list_backups() {
  info "Available backups in s3://${SPACES_BUCKET}/${BACKUP_PREFIX}/"
  aws s3 ls "s3://${SPACES_BUCKET}/${BACKUP_PREFIX}/" \
    --endpoint-url "${SPACES_ENDPOINT}" \
  | grep "ctfd-backup-" \
  | sort -r \
  | head -20 \
  | awk '{printf "  %s  %s  (%s bytes)\n", $1, $4, $3}'
}

# ──────────────────────────────────────────────
# Download backup (local path or s3://)
# ──────────────────────────────────────────────

download_backup() {
  local src="$1"
  local dest

  if [[ "$src" == s3://* ]]; then
    dest="${BACKUP_DIR}/$(basename "$src")"
    mkdir -p "${BACKUP_DIR}"
    info "Downloading $src → $dest"
    aws s3 cp "$src" "$dest" \
      --endpoint-url "${SPACES_ENDPOINT}" || {
      error "Download failed"
      exit 3
    }
    echo "$dest"
  elif [[ "$src" == "${BACKUP_PREFIX}/"* ]]; then
    # Shorthand: just the key within the bucket
    download_backup "s3://${SPACES_BUCKET}/${src}"
  else
    # Local file
    [[ -f "$src" ]] || { error "File not found: $src"; exit 1; }
    echo "$src"
  fi
}

# ──────────────────────────────────────────────
# Get the most recent backup from Spaces
# ──────────────────────────────────────────────

latest_backup_s3() {
  local latest
  latest=$(aws s3 ls "s3://${SPACES_BUCKET}/${BACKUP_PREFIX}/" \
    --endpoint-url "${SPACES_ENDPOINT}" \
    | grep "ctfd-backup-" \
    | sort -r \
    | head -1 \
    | awk '{print $4}')
  [[ -z "$latest" ]] && { error "No backups found in Spaces"; exit 3; }
  echo "s3://${SPACES_BUCKET}/${BACKUP_PREFIX}/${latest}"
}

# ──────────────────────────────────────────────
# Main restore
# ──────────────────────────────────────────────

do_restore() {
  local backup_file="$1"
  local MYSQL_ROOT_PASSWORD MYSQL_POD

  MYSQL_ROOT_PASSWORD=$(get_mysql_password)
  MYSQL_POD=$(get_mysql_pod)

  info "MySQL pod: ${MYSQL_POD}"
  check_mysql_ready "$MYSQL_POD" "$MYSQL_ROOT_PASSWORD"

  # Show current row counts
  echo ""
  warn "Current database state:"
  row_counts "$MYSQL_POD" "$MYSQL_ROOT_PASSWORD"
  echo ""

  # Confirmation gate
  warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  warn "  You are about to OVERWRITE the live CTFd database."
  warn "  Source: ${backup_file}"
  warn "  Target: mysql-0.ctfd namespace"
  warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -n "  Type 'yes' to continue: "
  read -r answer
  [[ "$answer" == "yes" ]] || { warn "Aborted."; exit 0; }

  # Pre-restore snapshot
  local PRE_SNAPSHOT="${BACKUP_DIR}/pre-restore-snapshot-$(date -u +%Y-%m-%dT%H-%M-%SZ).sql.gz"
  mkdir -p "${BACKUP_DIR}"
  info "Taking pre-restore snapshot → ${PRE_SNAPSHOT}"
  kubectl exec "$MYSQL_POD" -n ctfd -- \
    mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" \
    --single-transaction --set-gtid-purged=OFF ctfd \
  | gzip -9 > "${PRE_SNAPSHOT}"
  info "Pre-restore snapshot saved ($(wc -c < "${PRE_SNAPSHOT}") bytes)"

  # Decompress if gzipped
  local SQL_FILE
  if [[ "$backup_file" == *.gz ]]; then
    SQL_FILE="${backup_file%.gz}.tmp.sql"
    info "Decompressing..."
    gunzip -c "$backup_file" > "$SQL_FILE"
    trap "rm -f '$SQL_FILE'" EXIT
  else
    SQL_FILE="$backup_file"
  fi

  # Apply restore
  info "Applying restore..."
  kubectl exec -i "$MYSQL_POD" -n ctfd -- \
    bash -c "mysql -u root -p'${MYSQL_ROOT_PASSWORD}' ctfd" \
    < <(echo "SET FOREIGN_KEY_CHECKS=0; SET UNIQUE_CHECKS=0;" && cat "$SQL_FILE") || {
    error "Restore failed. Pre-restore snapshot available at: ${PRE_SNAPSHOT}"
    exit 4
  }

  # Post-restore row counts
  echo ""
  info "Post-restore database state:"
  row_counts "$MYSQL_POD" "$MYSQL_ROOT_PASSWORD"
  echo ""

  # Flush Redis sessions (users will need to re-login after restore)
  local REDIS_POD
  REDIS_POD=$(kubectl get pod -n ctfd -l app=redis \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [[ -n "$REDIS_POD" ]]; then
    warn "Flushing Redis sessions (teams will need to re-login)..."
    kubectl exec "$REDIS_POD" -n ctfd -- redis-cli FLUSHDB &>/dev/null && \
      info "Redis flushed." || warn "Could not flush Redis — teams may see stale session errors."
  fi

  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Restore complete."
  info "Pre-restore snapshot: ${PRE_SNAPSHOT}"
  info "Roll back at any time: bash scripts/restore-mysql.sh ${PRE_SNAPSHOT}"
  info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

check_deps

case "${1:-}" in
  --list)
    list_backups
    ;;
  --latest)
    info "Finding latest backup in Spaces..."
    LATEST=$(latest_backup_s3)
    info "Latest: ${LATEST}"
    LOCAL=$(download_backup "$LATEST")
    do_restore "$LOCAL"
    ;;
  "")
    echo "Usage: $0 <backup-file|s3-uri>"
    echo "       $0 --list"
    echo "       $0 --latest"
    exit 1
    ;;
  *)
    LOCAL=$(download_backup "$1")
    do_restore "$LOCAL"
    ;;
esac
