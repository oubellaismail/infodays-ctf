# Data Model: 100-Team Scaling (400 VUs)

**Feature**: 007-100-team-scaling | **Date**: 2026-04-02

## Entities

This feature is infrastructure-focused. Entities represent Kubernetes/Terraform resources rather than application data models.

### ProxySQL Deployment

| Attribute | Value | Notes |
|-----------|-------|-------|
| Name | `proxysql` | Deployment in `ctfd` namespace |
| Replicas | 2 | HA — survives single pod failure |
| Image | `proxysql/proxysql:2.x` | Official ProxySQL image |
| Client port | 6033 | MySQL wire protocol (client-facing) |
| Admin port | 6032 | Admin/stats interface (health checks) |
| CPU limit | 250m | Per replica |
| Memory limit | 256Mi | Per replica |
| CPU request | 100m | Per replica |
| Memory request | 128Mi | Per replica |

**Relationships**:
- CTFd pods → ProxySQL (port 6033) — client connections
- ProxySQL → MySQL (port 3306) — server connections (multiplexed)
- ProxySQL ← ProxySQL ConfigMap — configuration injection

### ProxySQL ConfigMap

| Attribute | Value | Notes |
|-----------|-------|-------|
| Name | `proxysql-config` | ConfigMap in `ctfd` namespace |
| mysql_servers | `mysql.ctfd.svc.cluster.local:3306` | Single writer, hostgroup 0 |
| mysql_users | `ctfd` | Same credentials as direct connection |
| max_connections | 50 | Server-side connection cap |
| connection_pool_size | 50 | Per-server pool |
| multiplexing | enabled | Core feature — reuse server connections |
| connect_timeout_server_max | 10000 | 10s queue timeout (FR-005a) |
| monitor_enabled | true | Health monitoring of MySQL backend |

### Dedicated MySQL Node Pool (Terraform)

| Attribute | Value | Notes |
|-----------|-------|-------|
| Name | `mysql-pool` | Terraform `digitalocean_kubernetes_node_pool` |
| Size | `s-4vcpu-16gb` | 4 vCPU, 16 GB RAM |
| Node count | 1 | Single dedicated node |
| Taint | `workload=mysql:NoSchedule` | Isolates from general workloads |
| Labels | `role: mysql` | For nodeSelector targeting |
| Region | fra1 | Same as cluster |

### MySQL StatefulSet (Modified)

| Attribute | Current | New | Notes |
|-----------|---------|-----|-------|
| Memory limit | 2Gi | 12Gi | Dedicated node has 16GB |
| CPU limit | 500m | 2000m | Dedicated node has 4 vCPU |
| Memory request | (unset) | 8Gi | Ensures scheduling on dedicated node |
| CPU request | (unset) | 1000m | Baseline guarantee |
| max-connections | 500 | 1000 | Headroom for ProxySQL + admin |
| innodb-buffer-pool-size | 512MB | 8GB | 50% of 16GB node |
| Toleration | (none) | `workload=mysql:NoSchedule` | Required for tainted node |
| NodeSelector | (none) | `doks.digitalocean.com/node-pool: mysql-pool` | Pin to dedicated node |

### General Node Pool (Modified via Terraform)

| Attribute | Current | New | Notes |
|-----------|---------|-----|-------|
| Node size | s-4vcpu-8gb | s-8vcpu-16gb | 16GB per node |
| Node count | 5 | 6 | 96GB total |
| Labels | `role: worker` | `role: worker` | Unchanged |

### CTFd Deployment (Modified)

| Attribute | Current | New | Notes |
|-----------|---------|-----|-------|
| Replicas | 5 | 10 | Doubled for 400 VUs |
| DATABASE_URL | `mysql+pymysql://ctfd:$(MYSQL_PASSWORD)@mysql/ctfd` | `mysql+pymysql://ctfd:$(MYSQL_PASSWORD)@proxysql:6033/ctfd` | Route through ProxySQL |
| Workers | 4 | 4 | Unchanged |
| Memory limit | 2Gi | 2Gi | Unchanged |
| CPU limit | 2000m | 2000m | Unchanged |

### Network Policy Changes (ctfd namespace)

| Policy | Action | Details |
|--------|--------|---------|
| `allow-ctfd-egress-mysql` | REMOVE | CTFd no longer connects directly to MySQL |
| `allow-ctfd-egress-proxysql` | ADD | CTFd pods → ProxySQL pods on port 6033 |
| `allow-proxysql-egress-mysql` | ADD | ProxySQL pods → MySQL pod on port 3306 |
| `allow-proxysql-ingress-ctfd` | ADD | ProxySQL accepts from CTFd pods on port 6033 |

### Load Test Profile (Modified)

| Attribute | Current | New | Notes |
|-----------|---------|-----|-------|
| VUs | 200 | 400 | 100 teams × 4 members |
| Teams | 50 | 100 | In K6_CTF_TEAMS JSON |
| Ramp-up | 50s | 100s | 1s per team (auto-scales) |
| Duration | 45min | 45min | Unchanged |
| Thresholds | p95<3s, err<1% | p95<3s, err<1% | Unchanged |

## State Transitions

### ProxySQL Connection Lifecycle

```
Client Request → ProxySQL Port 6033
  ├─ Pool has idle server connection → Assign immediately
  ├─ Pool full, queue not full → Queue (up to 10s timeout)
  │   ├─ Connection becomes available → Assign from queue
  │   └─ Timeout exceeded → Reject with error
  └─ Pool at max + queue full → Reject immediately
```

### Deployment Rollout Order

```
1. Terraform: Create mysql-node-pool → Wait for node ready
2. MySQL: Apply updated StatefulSet → Rolls to dedicated node
3. ProxySQL: Apply ConfigMap + Deployment → 2 replicas ready
4. NetworkPolicy: Apply updated rules → Remove direct CTFd→MySQL
5. CTFd: Apply updated Deployment → Rolls to 10 replicas (DATABASE_URL change triggers restart)
6. Load Test: Run k6 at 400 VUs → Validate SC-001 through SC-004
```
