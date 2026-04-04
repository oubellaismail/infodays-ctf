# Contract: ProxySQL Interface

**Feature**: 007-100-team-scaling | **Date**: 2026-04-02

## ProxySQL ↔ CTFd (Client Side)

**Protocol**: MySQL wire protocol (compatible with `mysql+pymysql` driver)
**Endpoint**: `proxysql.ctfd.svc.cluster.local:6033`
**Authentication**: Same MySQL credentials as direct connection (`ctfd` user from `ctfd-secrets`)

### Connection Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Host | `proxysql` | K8s Service name in `ctfd` namespace |
| Port | 6033 | ProxySQL client listen port |
| Database | `ctfd` | Default schema |
| Max client connections | 400+ | Limited by ProxySQL `mysql-max_connections` on client side |
| Queue timeout | 10s | Excess connections wait up to 10s before rejection |

### CTFd DATABASE_URL Format

```
mysql+pymysql://ctfd:${MYSQL_PASSWORD}@proxysql:6033/ctfd
```

### Error Behavior

| Condition | Client Sees |
|-----------|-------------|
| ProxySQL healthy, MySQL healthy | Normal query responses |
| ProxySQL healthy, MySQL down | Connection error (ProxySQL returns MySQL error) |
| ProxySQL queue full + timeout | Connection refused after 10s |
| All ProxySQL replicas down | Connection refused (K8s Service has no endpoints) |

## ProxySQL ↔ MySQL (Server Side)

**Protocol**: MySQL wire protocol
**Endpoint**: `mysql.ctfd.svc.cluster.local:3306`
**Authentication**: `ctfd` user credentials

### Connection Pool Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| max_connections | 50 | Maximum server-side connections to MySQL |
| connection_pool_size | 50 | Matches max_connections |
| Multiplexing | enabled | Multiple clients share server connections |
| Hostgroup | 0 (writer) | All queries route to single writer |

## ProxySQL Admin Interface

**Endpoint**: `localhost:6032` (pod-internal only)
**Purpose**: Health checks, stats collection, runtime config changes

### Health Check Contract

```
# Kubernetes readiness/liveness probe
mysql -h 127.0.0.1 -P 6032 -u admin -padmin -e "SELECT 1"
# Returns 0 on success, non-zero on failure
```

## Network Policy Contract

| Source | Destination | Port | Protocol | Policy Name |
|--------|-------------|------|----------|-------------|
| CTFd pods (app=ctfd) | ProxySQL pods (app=proxysql) | 6033 | TCP | allow-ctfd-egress-proxysql |
| ProxySQL pods (app=proxysql) | MySQL pod (app=mysql) | 3306 | TCP | allow-proxysql-egress-mysql |
| CTFd pods (app=ctfd) | ProxySQL pods (app=proxysql) | 6033 | TCP | allow-proxysql-ingress-ctfd |
