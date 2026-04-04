# Tasks: 100-Team Scaling (400 VUs)

**Input**: Design documents from `/specs/007-100-team-scaling/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: No dedicated test tasks — validation is via load testing (US1) and kubectl verification commands in quickstart.md.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Each task includes exact values and file paths so a model can implement without additional context.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Terraform**: `infra/terraform/` at repository root
- **K8s manifests**: `k8s/ctfd/` and `k8s/controller/` at repository root
- **Load tests**: `tests/load/` at repository root

---

## Phase 1: Setup

**Purpose**: No new project setup needed — this feature modifies existing files and adds a few new ones.

- [x] T001 Read all files that will be modified to understand current state: `infra/terraform/cluster.tf`, `infra/terraform/variables.tf`, `k8s/ctfd/mysql-statefulset.yaml`, `k8s/ctfd/deployment.yaml`, `k8s/ctfd/networkpolicy.yaml`, `tests/load/k6-ctf-scenario.js`

---

## Phase 2: Foundational (Terraform Node Pools)

**Purpose**: Provision the dedicated MySQL node and resize the general worker pool. MUST complete before any K8s manifest changes.

**CRITICAL**: No user story work can begin until this phase is complete. Terraform must create the MySQL node pool and resize the general pool before MySQL can be migrated or ProxySQL deployed.

- [x] T002 Update the `node_size` variable default from `"s-4vcpu-8gb"` to `"s-8vcpu-16gb"` in `infra/terraform/variables.tf`. Also update `node_count` default from `5` to `6`. Update any variable descriptions to reflect the new values.

- [x] T003 Update `infra/terraform/cluster.tf` — in the `digitalocean_kubernetes_cluster.infodays` resource's `node_pool` block, change `size` to reference `var.node_size` (if not already) and `node_count` to reference `var.node_count` (if not already). The resulting pool should be 6 × s-8vcpu-16gb.

- [x] T004 Create new file `infra/terraform/mysql-node-pool.tf` with a `digitalocean_kubernetes_node_pool` resource named `mysql`. Configuration:
  - `cluster_id = digitalocean_kubernetes_cluster.infodays.id`
  - `name = "mysql-pool"`
  - `size = "s-4vcpu-16gb"`
  - `node_count = 1`
  - `labels = { role = "mysql" }`
  - `taint` block: `key = "workload"`, `value = "mysql"`, `effect = "NoSchedule"`

**Checkpoint**: Run `terraform plan` to verify 2 changes: general pool resized + MySQL pool added. No K8s resources should be affected yet.

---

## Phase 3: User Story 3 — Database Runs on Dedicated High-Memory Infrastructure (Priority: P2)

**Goal**: Migrate MySQL StatefulSet to the dedicated tainted node with 12Gi memory and 8GB InnoDB buffer pool.

**Independent Test**: `kubectl get pods -n ctfd -l app=mysql -o wide` should show the MySQL pod running on a node from `mysql-pool`. `kubectl describe pod -n ctfd mysql-0` should show 12Gi memory limit and the toleration.

**Why US3 before US2**: MySQL must be running on the dedicated node before ProxySQL is deployed, because ProxySQL connects to MySQL. Migrating MySQL after ProxySQL is deployed would cause connection disruption.

### Implementation for User Story 3

- [x] T005 [US3] Modify `k8s/ctfd/mysql-statefulset.yaml` — in the StatefulSet's `spec.template.spec` section, add a `tolerations` array with one entry: `key: workload`, `operator: Equal`, `value: mysql`, `effect: NoSchedule`. Also add a `nodeSelector` with `doks.digitalocean.com/node-pool: mysql-pool`.

- [x] T006 [US3] Modify `k8s/ctfd/mysql-statefulset.yaml` — update the MySQL container's `resources` section. Set `limits.memory` to `12Gi` and `limits.cpu` to `2000m`. Add `requests.memory: 8Gi` and `requests.cpu: 1000m`.

- [x] T007 [US3] Modify `k8s/ctfd/mysql-statefulset.yaml` — update the container `args` array. Change `--max-connections=500` to `--max-connections=1000`. Change `--innodb-buffer-pool-size=536870912` to `--innodb-buffer-pool-size=8589934592` (this is 8GB in bytes).

**Checkpoint**: Apply the StatefulSet. MySQL pod should be rescheduled to the mysql-pool node. Verify with `kubectl get pods -n ctfd -l app=mysql -o wide`. The node name should correspond to a node in the mysql-pool. Run `kubectl exec -n ctfd mysql-0 -- mysql -u root -p"$MYSQL_ROOT_PASSWORD" -e "SHOW VARIABLES LIKE 'innodb_buffer_pool_size'"` to confirm 8GB.

---

## Phase 4: User Story 2 — Database Connection Pooling Eliminates Bottleneck (Priority: P1)

**Goal**: Deploy ProxySQL between CTFd and MySQL, update network policies, and switch CTFd to route through ProxySQL.

**Independent Test**: After this phase, `kubectl exec -n ctfd deploy/proxysql -- mysql -h 127.0.0.1 -P 6032 -u admin -padmin -e "SELECT * FROM stats_mysql_connection_pool"` should show active connections to MySQL. CTFd logs should show normal startup with no MySQL errors.

### Implementation for User Story 2

- [x] T008 [P] [US2] Create new file `k8s/ctfd/proxysql-configmap.yaml` — a ConfigMap named `proxysql-config` in namespace `ctfd`. It must contain a single data key `proxysql.cnf` with the following ProxySQL configuration (use YAML multiline string `|`):

  ```
  datadir="/var/lib/proxysql"

  admin_variables=
  {
      admin_credentials="admin:admin"
      mysql_ifaces="0.0.0.0:6032"
  }

  mysql_variables=
  {
      threads=4
      max_connections=2048
      default_query_delay=0
      default_query_timeout=36000000
      have_compress=true
      poll_timeout=2000
      interfaces="0.0.0.0:6033"
      default_schema="information_schema"
      stacksize=1048576
      server_version="8.0.35"
      connect_timeout_server=3000
      connect_timeout_server_max=10000
      monitor_username="ctfd"
      monitor_password="PLACEHOLDER_WILL_BE_OVERRIDDEN"
      monitor_history=600000
      monitor_connect_interval=60000
      monitor_ping_interval=10000
      monitor_read_only_interval=1500
      monitor_read_only_timeout=500
      ping_interval_server_msec=120000
      ping_timeout_server=500
      commands_stats=true
      sessions_sort=true
      connect_retries_on_failure=10
      connection_max_age_ms=0
      multiplexing=true
  }

  mysql_servers =
  (
      {
          address="mysql.ctfd.svc.cluster.local"
          port=3306
          hostgroup=0
          max_connections=50
          weight=1000
      }
  )

  mysql_users =
  (
      {
          username="ctfd"
          password="PLACEHOLDER_WILL_BE_OVERRIDDEN"
          default_hostgroup=0
          max_connections=1000
          active=1
      }
  )

  mysql_query_rules =
  (
      {
          rule_id=1
          active=1
          match_pattern=".*"
          destination_hostgroup=0
          apply=1
      }
  )
  ```

  **IMPORTANT**: The `monitor_password` and user `password` fields are placeholders. They will be overridden at runtime via environment variables (see T009). The ConfigMap itself must NOT contain real passwords.

- [x] T009 [P] [US2] Create new file `k8s/ctfd/proxysql-deployment.yaml` with a Deployment named `proxysql` in namespace `ctfd`, and a Service named `proxysql` in namespace `ctfd`.

  **Deployment spec**:
  - `replicas: 2`
  - `selector.matchLabels: { app: proxysql }`
  - `template.metadata.labels: { app: proxysql }`
  - Container name: `proxysql`
  - Image: `proxysql/proxysql:2.6.3` (use a specific tag, not `latest`)
  - Ports: `containerPort: 6033` (name: `mysql`) and `containerPort: 6032` (name: `admin`)
  - Volume mount: mount the ConfigMap `proxysql-config` at `/etc/proxysql.cnf` with `subPath: proxysql.cnf` (readOnly)
  - Environment variables from Secret `ctfd-secrets`:
    - `MYSQL_PASSWORD` from key `MYSQL_PASSWORD`
  - Add an `initContainers` entry that copies the ConfigMap config and substitutes the password placeholder. Use an init container with image `busybox:1.36`:
    - Command: `sh -c "cp /etc/proxysql-template/proxysql.cnf /var/lib/proxysql/proxysql.cnf && sed -i \"s/PLACEHOLDER_WILL_BE_OVERRIDDEN/$MYSQL_PASSWORD/g\" /var/lib/proxysql/proxysql.cnf"`
    - Mount ConfigMap `proxysql-config` at `/etc/proxysql-template/` (readOnly)
    - Mount an emptyDir volume `proxysql-data` at `/var/lib/proxysql/`
    - Env: `MYSQL_PASSWORD` from Secret `ctfd-secrets` key `MYSQL_PASSWORD`
  - Main container mounts `proxysql-data` emptyDir at `/var/lib/proxysql/`
  - Main container command: `["proxysql", "-f", "-c", "/var/lib/proxysql/proxysql.cnf", "--no-monitor"]` — note: remove `--no-monitor` once monitor credentials are verified working; alternatively start with monitor enabled.
  - Actually, use: `["proxysql", "-f", "-c", "/var/lib/proxysql/proxysql.cnf"]` to start with monitoring enabled.
  - Resources: `limits: { cpu: 250m, memory: 256Mi }`, `requests: { cpu: 100m, memory: 128Mi }`
  - Readiness probe: `exec.command: ["mysql", "-h", "127.0.0.1", "-P", "6032", "-u", "admin", "-padmin", "-e", "SELECT 1"]`, `initialDelaySeconds: 5`, `periodSeconds: 10`
  - Liveness probe: same as readiness, `initialDelaySeconds: 15`, `periodSeconds: 30`
  - Security context: `runAsNonRoot: false` (ProxySQL needs to bind to ports as its own user internally)
  - Volumes: `proxysql-config` (configMap, name: `proxysql-config`), `proxysql-data` (emptyDir)

  **Service spec**:
  - `name: proxysql`, `namespace: ctfd`
  - `type: ClusterIP`
  - `selector: { app: proxysql }`
  - Ports: `port: 6033, targetPort: 6033, name: mysql` and `port: 6032, targetPort: 6032, name: admin`

- [x] T010 [US2] Modify `k8s/ctfd/networkpolicy.yaml` — make these changes:

  1. **Remove** the existing `allow-ctfd-egress-mysql` NetworkPolicy entirely (the one that allows CTFd pods egress to MySQL on port 3306). CTFd will no longer connect directly to MySQL.

  2. **Add** a new NetworkPolicy named `allow-ctfd-egress-proxysql` in namespace `ctfd`:
     - `podSelector.matchLabels: { app: ctfd }`
     - `policyTypes: [Egress]`
     - `egress[0].to[0].podSelector.matchLabels: { app: proxysql }`
     - `egress[0].ports[0]: { port: 6033, protocol: TCP }`

  3. **Add** a new NetworkPolicy named `allow-proxysql-ingress-ctfd` in namespace `ctfd`:
     - `podSelector.matchLabels: { app: proxysql }`
     - `policyTypes: [Ingress]`
     - `ingress[0].from[0].podSelector.matchLabels: { app: ctfd }`
     - `ingress[0].ports[0]: { port: 6033, protocol: TCP }`

  4. **Add** a new NetworkPolicy named `allow-proxysql-egress-mysql` in namespace `ctfd`:
     - `podSelector.matchLabels: { app: proxysql }`
     - `policyTypes: [Egress]`
     - `egress[0].to[0].podSelector.matchLabels: { app: mysql }`
     - `egress[0].ports[0]: { port: 3306, protocol: TCP }`

  5. **Add** a new NetworkPolicy named `allow-proxysql-egress-dns` in namespace `ctfd`:
     - `podSelector.matchLabels: { app: proxysql }`
     - `policyTypes: [Egress]`
     - `egress[0].to[0].namespaceSelector.matchLabels: { kubernetes.io/metadata.name: kube-system }`
     - `egress[0].ports: [{ port: 53, protocol: UDP }, { port: 53, protocol: TCP }]`

  **IMPORTANT**: Keep ALL other existing NetworkPolicies in the file unchanged — do not remove `allow-controller-egress-k8s-api`, `allow-ctfd-egress-controller`, `allow-ctfd-to-controller-ingress`, `allow-ctfd-egress-dns`, `allow-ctfd-egress-redis`, etc.

- [x] T011 [US2] Modify `k8s/ctfd/deployment.yaml` — make TWO changes:

  1. Change `replicas` from `5` to `10`.

  2. Change the `DATABASE_URL` environment variable value from:
     `mysql+pymysql://ctfd:$(MYSQL_PASSWORD)@mysql/ctfd`
     to:
     `mysql+pymysql://ctfd:$(MYSQL_PASSWORD)@proxysql:6033/ctfd`

  **IMPORTANT**: Do NOT change any other values in this file — keep workers at 4, keep all resource limits, keep all health checks, keep all other env vars identical.

**Checkpoint**: Apply in order: `kubectl apply -f k8s/ctfd/proxysql-configmap.yaml`, then `kubectl apply -f k8s/ctfd/proxysql-deployment.yaml`, then `kubectl apply -f k8s/ctfd/networkpolicy.yaml`, then `kubectl apply -f k8s/ctfd/deployment.yaml`. Verify ProxySQL has 2/2 pods ready. Verify CTFd has 10/10 pods ready. Check ProxySQL stats: `kubectl exec -n ctfd deploy/proxysql -- mysql -h 127.0.0.1 -P 6032 -u admin -padmin -e "SELECT srv_host, ConnUsed, ConnFree, ConnOK, ConnERR FROM stats_mysql_connection_pool"`. ConnOK should be > 0 and ConnERR should be 0.

---

## Phase 5: User Story 4 — Challenge Pods Scale to 100 Teams (Priority: P2)

**Goal**: Verify that the resized cluster (6 × s-8vcpu-16gb = 96GB) can accommodate 1,500 Deployment objects and 400 running challenge pods.

**Independent Test**: Run `kubectl exec -n ctfd deploy/controller-api -- python bulk_spawn.py` for 100 teams and verify 1,500 Deployments are created. Activate 4 challenges per team for a subset of teams and verify pods schedule successfully.

### Implementation for User Story 4

- [x] T012 [US4] No file changes needed — the general node pool was already resized in T002/T003 (Phase 2). This task is a verification step: after Terraform apply, confirm 6 nodes of size s-8vcpu-16gb are ready with `kubectl get nodes -o wide`. Calculate available memory: each node has ~16GB, 6 nodes = ~96GB total. Subtract platform workloads (~22GB for 10 CTFd + ProxySQL + controller + ingress) = ~74GB available. 400 pods × 128Mi = ~51.2GB fits with ~23GB headroom.

- [x] T013 [US4] No file changes needed — verify bulk_spawn.py works with 100 teams. The existing `controller/bulk_spawn.py` already supports arbitrary team counts. The team list comes from CTFd API. Ensure 100 team accounts exist in CTFd before running bulk spawn. Verify with: `kubectl get deployments -n challenges --no-headers | wc -l` should show ~1,500 (100 teams × 15 challenges).

**Checkpoint**: All 1,500 Deployments at replicas=0. Activate a few challenges to verify pods schedule on the enlarged cluster.

---

## Phase 6: User Story 1 — Platform Handles 400 Concurrent Users (Priority: P1)

**Goal**: Update the k6 load test to simulate 400 VUs (100 teams × 4 members) and validate p95 < 3s, error rate < 1%.

**Independent Test**: Run `k6 run tests/load/k6-ctf-scenario.js` with 100-team credentials and verify thresholds pass.

### Implementation for User Story 1

- [x] T014 [US1] Modify `tests/load/k6-ctf-scenario.js` — change the `vus` option from `200` to `400`. This is in the `export const options = { ... }` block. The `duration` should remain `45m`. The `thresholds` should remain `http_req_duration: ['p(95)<3000']` and `http_req_failed: ['rate<0.01']`.

- [x] T015 [US1] Modify `tests/load/k6-ctf-scenario.js` — verify the team assignment formula works for 100 teams. The existing formula `TEAMS[Math.floor((__VU - 1) / 4) % TEAMS.length]` already correctly assigns 4 VUs per team and wraps around. With 400 VUs and 100 teams in the `K6_CTF_TEAMS` array, each team gets exactly 4 VUs. No code change needed unless the formula is different from this — just verify and document.

- [x] T016 [US1] Modify `tests/load/k6-ctf-scenario.js` — verify the login stagger scales correctly. The existing formula `sleep(Math.floor((__VU - 1) / 4) * 1.0)` produces a 100-second ramp for 100 teams (team 0 starts at t=0, team 99 starts at t=99s). No code change needed unless the sleep factor is different — just verify.

**Checkpoint**: Run the load test with 100-team credentials. All thresholds should pass: p95 < 3000ms, error rate < 1%. If thresholds fail, check ProxySQL stats for connection pool exhaustion and MySQL slow query log for lock contention.

---

## Phase 7: User Story 5 — Infrastructure Configuration Is Version-Controlled (Priority: P3)

**Goal**: Ensure CiliumNetworkPolicy and ClusterRole/ClusterRoleBinding for the controller are persisted in version control (not just cluster-applied).

**Independent Test**: `kubectl diff -f k8s/controller/cilium-networkpolicy.yaml` and `kubectl diff -f k8s/controller/cluster-rbac.yaml` should show no differences.

### Implementation for User Story 5

- [x] T017 [US5] Verify that `k8s/controller/cilium-networkpolicy.yaml` already exists and contains the CiliumNetworkPolicy `allow-controller-to-kube-apiserver` in namespace `ctfd`. This file was created in Phase 5 of the project. Read the file and confirm it matches the cluster-applied resource. If the file exists and is correct, this task is already done.

- [x] T018 [US5] Verify that `k8s/controller/cluster-rbac.yaml` already exists and contains the ClusterRole `ctf-controller-nodes` (verbs: list, get on nodes) and ClusterRoleBinding `ctf-controller-nodes` binding to ServiceAccount `ctf-controller` in namespace `ctfd`. This file was created in Phase 5 of the project. Read the file and confirm it matches the cluster-applied resource. If the file exists and is correct, this task is already done.

**Checkpoint**: Both files exist in git and match cluster state. If either is missing, export from cluster with `kubectl get <resource> -o yaml` and save to the appropriate file path.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and documentation updates

- [x] T019 Run the full deployment sequence from quickstart.md (specs/007-100-team-scaling/quickstart.md) end-to-end and verify each step succeeds
- [x] T020 Verify all success criteria from spec.md are met:
  - SC-001: p95 < 3s at 400 VUs (from load test results)
  - SC-002: Error rate < 1% (from load test results)
  - SC-003: ProxySQL server connections ≤ 50 (from ProxySQL admin stats)
  - SC-004: No OOM kills or restarts during 45-min test (from `kubectl get events -n ctfd`)
  - SC-005: All 100 teams can log in concurrently (from load test login phase)
  - SC-006: TCP ports accessible via NodePort (spot-check a few)
  - SC-007: CiliumNetworkPolicy + ClusterRole in git (T017, T018)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — read-only orientation
- **Phase 2 (Foundational — Terraform)**: Depends on Phase 1 — BLOCKS all subsequent phases
- **Phase 3 (US3 — MySQL migration)**: Depends on Phase 2 (MySQL node must exist)
- **Phase 4 (US2 — ProxySQL)**: Depends on Phase 3 (MySQL must be on dedicated node)
- **Phase 5 (US4 — Challenge scaling)**: Depends on Phase 2 (general pool must be resized). Can run in PARALLEL with Phase 3 and Phase 4.
- **Phase 6 (US1 — Load test)**: Depends on Phase 4 (ProxySQL + CTFd must be reconfigured)
- **Phase 7 (US5 — Version control)**: No dependencies on other user stories — can run in PARALLEL with any phase
- **Phase 8 (Polish)**: Depends on all other phases

### User Story Dependencies

- **US3 (Dedicated MySQL node)**: Must complete BEFORE US2. MySQL must be on the dedicated node before ProxySQL is deployed.
- **US2 (ProxySQL)**: Must complete BEFORE US1 load testing. The load test validates the full ProxySQL + scaled CTFd stack.
- **US4 (Challenge scaling)**: Independent of US2 and US3. Only depends on Terraform (Phase 2).
- **US1 (Load test)**: Depends on US2 and US3 being complete. This is the final validation.
- **US5 (Version control)**: Fully independent — can run anytime.

### Within Each User Story

- Terraform (Phase 2) before K8s manifest changes
- MySQL migration (Phase 3) before ProxySQL deployment (Phase 4)
- ProxySQL + network policies before CTFd deployment changes (within Phase 4)
- All infrastructure changes before load test (Phase 6)

### Parallel Opportunities

- T002 and T004 can run in parallel (different Terraform files)
- T005, T006, and T007 all modify the same file (`mysql-statefulset.yaml`) — must be sequential
- T008 and T009 can run in parallel (different new files)
- T012, T013 (US4 verification) can run in parallel with T008-T011 (US2 implementation)
- T017 and T018 (US5 verification) can run in parallel with any other phase
- T014, T015, T016 all modify the same file (`k6-ctf-scenario.js`) — T014 is the only code change; T015 and T016 are verification-only

---

## Parallel Example: Phase 4 (User Story 2)

```bash
# These two tasks create NEW files and can run in parallel:
Task T008: "Create ProxySQL ConfigMap in k8s/ctfd/proxysql-configmap.yaml"
Task T009: "Create ProxySQL Deployment + Service in k8s/ctfd/proxysql-deployment.yaml"

# Then sequentially (modifies existing files, depends on T008/T009 being applied first):
Task T010: "Update network policies in k8s/ctfd/networkpolicy.yaml"
Task T011: "Update CTFd deployment in k8s/ctfd/deployment.yaml"
```

---

## Implementation Strategy

### MVP First (US3 + US2 = Database Fix)

1. Complete Phase 2: Terraform node pools
2. Complete Phase 3: MySQL to dedicated node (US3)
3. Complete Phase 4: ProxySQL + CTFd reconfiguration (US2)
4. **STOP and VALIDATE**: Run quick smoke test (manual `curl` to CTFd, check ProxySQL stats)
5. This alone should dramatically reduce p95 latency

### Incremental Delivery

1. Phase 2 (Terraform) → Foundation ready
2. Phase 3 (US3) + Phase 4 (US2) → Database bottleneck eliminated (MVP!)
3. Phase 5 (US4) → Challenge scaling verified
4. Phase 6 (US1) → Load test validates everything
5. Phase 7 (US5) → Git hygiene
6. Phase 8 → Final sign-off

### Single-Implementer Order

For a single LLM agent implementing sequentially:
1. T001 → T002 → T003 → T004 (Terraform)
2. T005 → T006 → T007 (MySQL StatefulSet — same file, sequential)
3. T008 + T009 in parallel (new ProxySQL files)
4. T010 → T011 (network policy then CTFd deployment)
5. T014 (load test VU change — T015/T016 are verify-only)
6. T017 + T018 in parallel (verify existing files)
7. T019 → T020 (final validation)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Tasks T012, T013, T015, T016, T017, T018 are verification-only (no file changes) — they confirm existing code/infrastructure meets requirements
- The ProxySQL password injection uses an init container + sed to avoid storing real passwords in the ConfigMap
- Apply order matters: Terraform first, then MySQL migration, then ProxySQL, then network policies, then CTFd deployment change
- If load test fails, check ProxySQL stats first (`stats_mysql_connection_pool`) — ConnERR > 0 indicates MySQL backend issues
