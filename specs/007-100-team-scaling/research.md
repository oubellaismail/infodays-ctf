# Research: 100-Team Scaling (400 VUs)

**Feature**: 007-100-team-scaling | **Date**: 2026-04-02

## R1: ProxySQL Connection Pooling Configuration

**Decision**: Deploy ProxySQL 2.x as a Deployment (2 replicas) in the `ctfd` namespace, configured in multiplexing mode with 50 max server-side connections.

**Rationale**: ProxySQL is the industry-standard MySQL connection pooler for write-heavy workloads. Unlike PgBouncer (PostgreSQL only) or application-level pooling (e.g., SQLAlchemy pool), ProxySQL operates at the wire protocol level and supports true connection multiplexing — reusing server connections across different client sessions. This directly addresses the bottleneck: 20+ persistent connections competing for row locks on CTFd's submissions table.

**Alternatives considered**:
- **MySQL Router**: Native MySQL proxy but lacks multiplexing; only connection routing. Would not reduce server-side connection count.
- **Application-level pooling (SQLAlchemy)**: CTFd uses SQLAlchemy internally, but its pool is per-process. 10 replicas × 4 workers = 40 pools = 40 persistent connections. No reduction.
- **HAProxy TCP mode**: Can load-balance connections but cannot multiplex — each client gets a dedicated server connection.

**Key configuration decisions**:
- `mysql-max_connections` (server-side): 50. With 400+ client connections multiplexed into 50 server connections, contention drops from 40:1 (direct) to ~8:1 per server connection.
- `mysql-connection_pool_size`: 50 per server (matches max_connections).
- `mysql-query_rules`: All traffic to single writer (hostgroup 0). No read/write split in v1.
- `mysql-monitor_enabled`: true. ProxySQL monitors MySQL health via admin interface.
- Client connection timeout (FR-005a): `mysql-connect_timeout_server_max` = 10000ms (10s queue, then reject).
- Admin interface on port 6032 for health checks and stats.

## R2: Dedicated MySQL Node Pool

**Decision**: Add a Terraform-managed node pool with 1 × s-4vcpu-16gb instance, tainted `workload=mysql:NoSchedule`, in region fra1.

**Rationale**: MySQL needs dedicated I/O and memory. On shared nodes, CTFd/challenge pods compete for CPU and memory bandwidth, causing MySQL OOM kills observed in Phase 6 (Run 2: 3.31% error rate from MySQL OOM). A dedicated 16GB node allows 12Gi allocation to MySQL with 8GB InnoDB buffer pool (50% of available RAM).

**Alternatives considered**:
- **Larger shared nodes**: Would not isolate MySQL I/O; other pods could still cause memory pressure.
- **DO Managed MySQL**: Violates constitution (Principle IV: K8s Secrets only, no external managed services). Also adds latency and removes control over tuning.
- **Multiple MySQL nodes with replication**: Out of scope per spec; adds complexity unnecessary for single-event use case.

**Key configuration decisions**:
- Taint: `workload=mysql:NoSchedule` — prevents all non-MySQL pods from scheduling.
- MySQL toleration: `workload=mysql:NoSchedule` added to StatefulSet.
- NodeSelector: `doks.digitalocean.com/node-pool: mysql-pool`.
- MySQL args: `--max-connections=1000`, `--innodb-buffer-pool-size=8589934592` (8GB).
- Resource limits: 12Gi RAM / 2 CPU. Resource requests: 8Gi RAM / 1 CPU.

## R3: General Node Pool Sizing

**Decision**: Upgrade general pool from 5 × s-4vcpu-8gb to 6 × s-8vcpu-16gb (96GB total, ~83GB usable after system overhead).

**Rationale**: 400 challenge pods × 128Mi = 51.2GB. Platform workloads (10 CTFd × 2Gi + 2 ProxySQL × 256Mi + controller + ingress + cert-manager) ≈ 22GB. Total ≈ 73GB. With 5 × 8GB = 40GB, this is impossible. 6 × 16GB = 96GB provides ~23GB headroom for scheduling overhead and burst.

**Alternatives considered**:
- **10 × s-4vcpu-8gb (80GB)**: Fits capacity but with only 7GB headroom. More nodes means more inter-node networking overhead and higher scheduling complexity.
- **4 × s-8vcpu-16gb (64GB)**: Insufficient — only ~41GB available after platform, which barely covers 320 challenge pods.
- **Reduce active cap from 4 to 2**: Rejected in clarification — 4 active challenges per team is a core event design constraint.

## R4: CTFd Scale-Out Strategy

**Decision**: Increase CTFd replicas from 5 to 10, keeping 4 workers per replica.

**Rationale**: With ProxySQL handling connection pooling, adding CTFd replicas no longer worsens database contention. 10 replicas × 4 workers = 40 Gunicorn processes, providing sufficient request throughput for 400 concurrent users. Anti-affinity preferred (soft) to spread replicas across nodes.

**Alternatives considered**:
- **8 replicas × 5 workers**: Same total workers (40) but higher per-pod memory. 5 workers × ~400MB = 2GB per pod at limit.
- **5 replicas × 8 workers**: Tested in Phase 6 Run 2 — caused MySQL OOM with 17,540ms p95. Fewer replicas means less horizontal resilience.
- **15 replicas × 2-3 workers**: Excessive scheduling overhead for marginal benefit.

## R5: etcd Capacity at 1,500 Deployments

**Decision**: Accept 1,500 Deployment objects as within standard DOKS etcd capacity. Monitor etcd latency during bulk spawn.

**Rationale**: Default etcd storage limit on DOKS is 8GB. Each Deployment object is ~2-5KB in etcd. 1,500 Deployments + 1,500 Secrets + 1,500 Services ≈ 4,500 objects × 5KB = ~22.5MB — well within limits. Standard Kubernetes clusters handle 100,000+ objects.

**Alternatives considered**:
- **Lazy spawning**: Create resources on-demand instead of pre-spawning. Violates constitution Principle III (pre-spawn model only).
- **Reducing challenge count**: Would limit event content; unnecessary given etcd capacity analysis.

## R6: TCP Port Scaling to 1,000 Ports

**Decision**: Continue using NodePort services (range 30000-32767) with direct node IP access. No load balancer involvement for TCP challenges.

**Rationale**: DigitalOcean Load Balancer has a 40 forwarding-rule limit. 100 teams × 10 TCP challenges = 1,000 ports — far exceeds this limit. NodePort approach is already in production (Phase 5+). The Kubernetes NodePort range supports 2,767 ports, so 1,000 is well within capacity.

**Alternatives considered**:
- **HAProxy/Envoy DaemonSet**: Would provide TCP load balancing across nodes but adds operational complexity. For a single-event deployment, NodePort is sufficient.
- **Multiple DO Load Balancers**: Would require complex routing rules and increase cost. One LB per 40 rules = 25 LBs — impractical.

## R7: Network Policy Updates for ProxySQL

**Decision**: Add two network policy rules: CTFd pods → ProxySQL (port 6033) egress, and ProxySQL → MySQL (port 3306) egress. Remove direct CTFd → MySQL egress rule.

**Rationale**: ProxySQL becomes the sole path from CTFd to MySQL. The existing `allow-ctfd-egress-mysql` rule (CTFd → MySQL:3306) should be replaced with CTFd → ProxySQL:6033, and a new ProxySQL → MySQL:3306 rule added. This maintains the default-deny posture while routing traffic through the pooler.

**Alternatives considered**:
- **Keep direct CTFd → MySQL rule alongside ProxySQL**: Creates a bypass path; defeats the purpose of connection pooling.

## R8: Load Test Updates

**Decision**: Scale k6 test to 400 VUs, 100 teams, 100-second ramp-up. Same scenario steps and thresholds.

**Rationale**: Linear scaling of the existing validated test. Team assignment formula `Math.floor((__VU - 1) / 4) % TEAMS.length` already supports arbitrary team counts. Ramp-up scales linearly: 100 teams × 1s/team = 100s (vs. 50s for 50 teams).

**Key changes**:
- `vus`: 200 → 400
- `K6_CTF_TEAMS` array: 50 → 100 team entries
- Login stagger: `sleep(Math.floor((__VU - 1) / 4) * 1.0)` unchanged (automatically scales to 100s)
- Duration: 45 minutes (unchanged)
- Thresholds: p95 < 3000ms, error < 1% (unchanged)
