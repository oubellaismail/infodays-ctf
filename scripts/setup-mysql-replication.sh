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
  CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED WITH mysql_native_password BY '${MYSQL_PASS}';
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

if echo "$REPLICA_STATUS" | grep -q "Replica_IO_Running: Yes"; then
  echo "Replication already running. Current status:"
  echo "$REPLICA_STATUS" | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind"
  exit 0
fi

# 4. Configure replication on replica
echo "Configuring GTID replication..."
kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"${MYSQL_PASS}" -e "
  STOP REPLICA;
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='mysql.ctfd.svc.cluster.local',
    SOURCE_PORT=3306,
    SOURCE_USER='repl',
    SOURCE_PASSWORD='${MYSQL_PASS}',
    SOURCE_AUTO_POSITION=1;
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
echo ""
echo "Setup complete."
