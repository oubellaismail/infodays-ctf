#!/usr/bin/env bash
# setup-mysql-replication.sh — Reseed MySQL replica and enable ProxySQL read routing.
#
# This script intentionally rebuilds only the replica. It does not drop or modify
# primary CTFd data. It is safe to run when mysql-replica is stale, missing CTFd
# tables, or stopped on a replication SQL error.

set -euo pipefail

NS="ctfd"
PRIMARY="mysql-0"
REPLICA="mysql-replica-0"

base64_decode() {
  if base64 --decode >/dev/null 2>&1 <<<""; then
    base64 --decode
  else
    base64 -D
  fi
}

sql_escape() {
  sed -e 's/\\/\\\\/g' -e "s/'/''/g" <<<"$1"
}

require_pod_ready() {
  local pod="$1"
  local ready
  ready="$(kubectl get pod "$pod" -n "$NS" -o jsonpath='{.status.containerStatuses[0].ready}')"
  if [[ "$ready" != "true" ]]; then
    echo "ERROR: ${NS}/${pod} is not ready" >&2
    exit 1
  fi
}

mysql_root() {
  local pod="$1"
  shift
  kubectl exec -n "$NS" "$pod" -- mysql -uroot -p"$MYSQL_PASS" "$@"
}

echo "=== MySQL Replica Reseed + Read Routing Setup ==="

MYSQL_PASS="$(kubectl get secret ctfd-secrets -n "$NS" -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64_decode)"
CTFD_PASS="$(kubectl get secret ctfd-secrets -n "$NS" -o jsonpath='{.data.MYSQL_PASSWORD}' | base64_decode)"
MYSQL_PASS_SQL="$(sql_escape "$MYSQL_PASS")"
CTFD_PASS_SQL="$(sql_escape "$CTFD_PASS")"

require_pod_ready "$PRIMARY"
require_pod_ready "$REPLICA"

echo "Creating replication user on primary..."
mysql_root "$PRIMARY" -e "
  DROP USER IF EXISTS 'repl'@'%';
  CREATE USER 'repl'@'%' IDENTIFIED BY '${MYSQL_PASS_SQL}';
  GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
  FLUSH PRIVILEGES;
" 2>/dev/null
echo "  done"

echo "Resetting replica state..."
mysql_root "$REPLICA" -e "
  STOP REPLICA;
  RESET REPLICA ALL;
  SET GLOBAL super_read_only=OFF;
  SET GLOBAL read_only=OFF;
  DROP DATABASE IF EXISTS ctfd;
  RESET BINARY LOGS AND GTIDS;
" 2>/dev/null
echo "  done"

echo "Dumping primary and importing into replica..."
kubectl exec -n "$NS" "$PRIMARY" -- \
  mysqldump -uroot -p"$MYSQL_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    --set-gtid-purged=ON \
    --databases ctfd \
  | kubectl exec -i -n "$NS" "$REPLICA" -- mysql -uroot -p"$MYSQL_PASS"
echo "  done"

echo "Granting CTFd read access on replica..."
mysql_root "$REPLICA" -e "
  CREATE USER IF NOT EXISTS 'ctfd'@'%' IDENTIFIED BY '${CTFD_PASS_SQL}';
  ALTER USER 'ctfd'@'%' IDENTIFIED BY '${CTFD_PASS_SQL}';
  GRANT SELECT ON ctfd.* TO 'ctfd'@'%';
  FLUSH PRIVILEGES;
" 2>/dev/null
echo "  done"

echo "Starting GTID auto-position replication..."
mysql_root "$REPLICA" -e "
  CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='mysql.ctfd.svc.cluster.local',
    SOURCE_PORT=3306,
    SOURCE_USER='repl',
    SOURCE_PASSWORD='${MYSQL_PASS_SQL}',
    SOURCE_AUTO_POSITION=1,
    GET_SOURCE_PUBLIC_KEY=1;
  START REPLICA;
  SET GLOBAL read_only=ON;
  SET GLOBAL super_read_only=ON;
" 2>/dev/null
echo "  done"

echo "Verifying replica health..."
sleep 3
STATUS="$(mysql_root "$REPLICA" -e "SHOW REPLICA STATUS\G" 2>/dev/null)"
echo "$STATUS" | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind_Source|Last_IO_Error|Last_SQL_Error"

if ! grep -q "Replica_IO_Running: Yes" <<<"$STATUS" || \
   ! grep -q "Replica_SQL_Running: Yes" <<<"$STATUS"; then
  echo "ERROR: replica is not healthy; leaving ProxySQL routing unchanged" >&2
  exit 1
fi

echo "Applying ProxySQL read/write split..."
kubectl apply -f k8s/ctfd/networkpolicy.yaml
kubectl delete networkpolicy allow-ctfd-egress-internet -n "$NS" --ignore-not-found >/dev/null
if ! kubectl get secret proxysql-admin -n "$NS" >/dev/null 2>&1; then
  PROXYSQL_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)"
  kubectl create secret generic proxysql-admin \
    --from-literal=PROXYSQL_ADMIN_PASSWORD="$PROXYSQL_ADMIN_PASSWORD" \
    -n "$NS" >/dev/null
  unset PROXYSQL_ADMIN_PASSWORD
fi
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl rollout restart deployment/proxysql -n "$NS"
kubectl rollout status deployment/proxysql -n "$NS" --timeout=300s

echo "Verifying ProxySQL routing..."
PROXYSQL_ADMIN_PASSWORD="$(kubectl get secret proxysql-admin -n "$NS" -o jsonpath='{.data.PROXYSQL_ADMIN_PASSWORD}' | base64 -d)"
kubectl exec -n "$NS" deployment/proxysql -- env MYSQL_PWD="$PROXYSQL_ADMIN_PASSWORD" mysql -h127.0.0.1 -P6032 -uadmin -e "
  SELECT hostgroup_id, hostname, status FROM runtime_mysql_servers ORDER BY hostgroup_id, hostname;
  SELECT rule_id, active, match_pattern, destination_hostgroup, apply FROM runtime_mysql_query_rules ORDER BY rule_id;
  SELECT hostgroup, srv_host, status, ConnERR, Queries FROM stats.stats_mysql_connection_pool ORDER BY hostgroup;
" 2>/dev/null
unset PROXYSQL_ADMIN_PASSWORD

echo "Setup complete: normal SELECTs route to mysql-replica; writes and write-intent reads route to mysql."
