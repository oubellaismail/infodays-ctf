#!/usr/bin/env bash
# setup-mysql-replication.sh — Configure MySQL GTID-based replication
#
# Prereqs:
#   - mysql primary running with --gtid-mode=ON --log-bin
#   - mysql-replica running with --gtid-mode=ON --read-only=ON
#   - Both share MYSQL_ROOT_PASSWORD from ctfd-secrets
#
# Idempotent: safe to re-run. Checks replica status before configuring.

set -euo pipefail

echo "=== MySQL Replication Setup ==="

MYSQL_PASS=$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)
CTFD_PASS=$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_PASSWORD}' | base64 -d)

# 1. Create replication user on primary (idempotent, use mysql_native_password to avoid
# caching_sha2_password secure-connection requirement for replication)
echo "Creating replication user on primary..."
kubectl exec -n ctfd mysql-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "
  DROP USER IF EXISTS 'repl'@'%';
  CREATE USER 'repl'@'%' IDENTIFIED BY '${MYSQL_PASS}';
  GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
  FLUSH PRIVILEGES;
" 2>/dev/null
echo "  done"

# 2. Grant SELECT on ctfd.* to ctfd user on replica (for ProxySQL reads)
# Uses CTFD_PASS (MYSQL_PASSWORD), not root password — must match what CTFd sends through ProxySQL
echo "Granting read access on replica..."
kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "
  CREATE USER IF NOT EXISTS 'ctfd'@'%' IDENTIFIED BY '${CTFD_PASS}';
  GRANT SELECT ON ctfd.* TO 'ctfd'@'%';
  FLUSH PRIVILEGES;
" 2>/dev/null
echo "  done"

# 3. Check if replica is already replicating
REPLICA_STATUS=$(kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "SHOW REPLICA STATUS\G" 2>/dev/null || true)

if echo "$REPLICA_STATUS" | grep -q "Replica_IO_Running: Yes" && \
   echo "$REPLICA_STATUS" | grep -q "Replica_SQL_Running: Yes"; then
  echo "Replication already running (both IO and SQL threads up). Current status:"
  echo "$REPLICA_STATUS" | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind"
  exit 0
fi
# If IO thread is up but SQL thread is not (stopped on error), fall through to re-configure

# 4. Configure replication on replica
echo "Configuring GTID replication..."

# Get primary's current GTID set to start replication from "now" (skipping historical DDL/DML
# that was already applied directly to replica during setup, which would cause duplicate key errors)
PRIMARY_GTID=$(kubectl exec -n ctfd mysql-0 -- mysql -uroot -p"${MYSQL_PASS}" \
  -e "SELECT @@global.gtid_executed;" 2>/dev/null | tail -1 | tr -d ' \t')
echo "  Primary GTID: $PRIMARY_GTID"

kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "
  STOP REPLICA;
  RESET REPLICA ALL;
  RESET BINARY LOGS AND GTIDS;
  SET GLOBAL gtid_purged='${PRIMARY_GTID}';
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='mysql.ctfd.svc.cluster.local',
    SOURCE_PORT=3306,
    SOURCE_USER='repl',
    SOURCE_PASSWORD='${MYSQL_PASS}',
    SOURCE_AUTO_POSITION=1,
    GET_SOURCE_PUBLIC_KEY=1;
  START REPLICA;
" 2>/dev/null
echo "  done"

# 5. Verify replication is running
sleep 3
echo ""
echo "=== Replication Status ==="
kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "SHOW REPLICA STATUS\G" 2>/dev/null | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind|Last_Error"

# 6. Enable read-only on replica (after replication is configured)
echo ""
echo "Enabling read-only mode on replica..."
kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "
  SET GLOBAL read_only=ON;
  SET GLOBAL super_read_only=ON;
" 2>/dev/null
echo "  done"

# 7. Point ProxySQL hostgroup 1 (reader) at the replica
# The configmap ships with both hostgroups pointing at the primary as a safe default.
# Now that replication is confirmed healthy, patch hostgroup 1 to use mysql-replica.
echo ""
echo "Updating ProxySQL configmap — routing reads to replica..."

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
CONFIGMAP="${REPO_ROOT}/k8s/ctfd/proxysql-configmap.yaml"

# Check if the configmap already points to the replica (idempotent)
if grep -q 'mysql-replica.ctfd.svc.cluster.local' "$CONFIGMAP"; then
  echo "  ProxySQL configmap already points to replica — skipping patch"
else
  # Replace only the hostgroup=1 entry's address (second occurrence of the primary hostname)
  awk '
    /address="mysql\.ctfd\.svc\.cluster\.local"/ {
      count++
      if (count == 2) {
        sub(/address="mysql\.ctfd\.svc\.cluster\.local"/, "address=\"mysql-replica.ctfd.svc.cluster.local\"")
      }
    }
    { print }
  ' "$CONFIGMAP" > "${CONFIGMAP}.tmp" && mv "${CONFIGMAP}.tmp" "$CONFIGMAP"
  echo "  Configmap updated on disk"
fi

kubectl apply -f "$CONFIGMAP"
kubectl rollout restart deployment/proxysql -n ctfd
kubectl rollout status deployment/proxysql -n ctfd --timeout=60s

echo "  done — SELECT queries now route to mysql-replica"
echo ""
echo "Verify routing:"
echo "  kubectl exec -n ctfd deployment/proxysql -- mysql -h127.0.0.1 -P6032 -uadmin -padmin \\"
echo "    -e \"SELECT hostgroup,srv_host,status,ConnUsed FROM stats.stats_mysql_connection_pool;\""
echo ""
echo "Setup complete."
