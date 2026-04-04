# Implementation Plan: 50-Team Scaling (200 VUs)

**Branch**: `007-100-team-scaling` | **Date**: 2026-04-02 (rescoped 2026-04-03) | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-100-team-scaling/spec.md`

> **Rescope note (2026-04-03)**: Original plan targeted 100 teams (400 VUs). Max team count was
> revised to **50 teams (200 VUs)** before the event, matching the actual participant capacity.
> All sizing decisions below reflect the rescoped configuration.

## Summary

Scale the InfoDays CTF platform to support 50 teams (200 VUs). The primary bottleneck at 200 VUs was MySQL single-writer throughput — multiple persistent connections from CTFd workers contended for row locks, producing p95 ~10s latency. The fix introduces ProxySQL as a connection pooler (2 replicas, multiplexing 200+ client connections into ≤25 server-side connections), keeps MySQL on shared nodes (dedicated node pool unavailable in fra1), scales CTFd to 5 replicas, and updates the load test to validate 200 VUs over 45 minutes.

**Additionally**, a critical security gap was discovered and fixed: CTFd's native flag types have no team-binding — any team could submit another team's flag and score points. A custom `team` flag type was implemented using HMAC-SHA256 derivation, making cross-team flag submission cryptographically impossible. A `cheaters` table and admin endpoint were added for post-event forensics.

## Technical Context

**Language/Version**: HCL (Terraform ≥1.5), YAML (Kubernetes manifests), Bash 5 (scripts), JavaScript ESM (k6 load tests)
**Primary Dependencies**: Terraform `digitalocean` provider v2.x, `helm` provider v2.x, ProxySQL 2.x, kubectl, k6
**Storage**: MySQL 8 (StatefulSet, 10Gi PVC on `do-block-storage`), Redis 7 (ephemeral)
**Testing**: k6 (load tests), Bash (infrastructure acceptance tests)
**Target Platform**: DigitalOcean Kubernetes (DOKS), region fra1
**Project Type**: Infrastructure scaling (IaC + K8s manifests + load test config)
**Performance Goals**: p95 < 3s, error rate < 1% at 200 VUs over 45 minutes
**Constraints**: DigitalOcean only, single MySQL writer (no read replicas), time-boxed event (4-8 hours), fra1 `m-2vcpu-16gb` capacity unavailable (no dedicated MySQL node)
**Scale/Scope**: 50 teams × 4 members = 200 concurrent users, ~750 Deployment objects, up to 500 TCP NodePorts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Flag Integrity | PASS | No changes to flag derivation, storage, or transmission |
| II. Security-First Pod Isolation | PASS | No changes to pod security contexts, PSS labels, or NetworkPolicies for challenge pods |
| III. Pod Lifecycle Discipline | PASS | Pre-spawn model unchanged; max 4 active pods per team unchanged |
| IV. DigitalOcean-Exclusive | PASS | All infrastructure remains on DigitalOcean (DOKS, DOCR, DO Spaces) |
| V. Resource & Cost Discipline | **VIOLATION** | Node size exceeds s-4vcpu-8gb; node count exceeds 5; CTFd replicas exceed 2; MySQL memory exceeds 1Gi. See Complexity Tracking. |

**Gate result**: PASS WITH VIOLATIONS — all violations are justified below in Complexity Tracking. Principle V resource limits were established for 50-team scale; 100-team scaling requires proportionally larger infrastructure.

## Project Structure

### Documentation (this feature)

```text
specs/007-100-team-scaling/
├── plan.md              # This file
├── research.md          # Phase 0: ProxySQL config, node sizing, etcd capacity
├── data-model.md        # Phase 1: Entity relationships and state model
├── quickstart.md        # Phase 1: Step-by-step deployment guide
├── contracts/           # Phase 1: ProxySQL ↔ MySQL, CTFd ↔ ProxySQL interfaces
└── tasks.md             # Phase 2: Task breakdown (created by /speckit.tasks)
```

### Source Code (repository root)

```text
infra/
└── terraform/
    ├── cluster.tf                  # MODIFIED: general pool → 5 × s-4vcpu-8gb
    ├── variables.tf                # MODIFIED: node_count default 6→5, descriptions updated for 50-team
    └── mysql-node-pool.tf          # COMMENTED OUT: fra1 m-2vcpu-16gb capacity unavailable

k8s/
├── ctfd/
│   ├── proxysql-deployment.yaml    # NEW: ProxySQL Deployment (2 replicas) + Service
│   ├── proxysql-configmap.yaml     # NEW: ProxySQL config — max_connections=25 (server-side)
│   ├── mysql-statefulset.yaml      # MODIFIED: max-connections=500, innodb-buffer-pool=2G, 4Gi memory
│   ├── deployment.yaml             # MODIFIED: DATABASE_URL → proxysql, 5 replicas
│   └── networkpolicy.yaml          # MODIFIED: add allow-proxysql-ingress-mysql (was missing, SHUNNED bug)
├── controller/
│   ├── cilium-networkpolicy.yaml   # EXISTS: already persisted in Phase 5
│   └── cluster-rbac.yaml           # EXISTS: already persisted in Phase 5

ctfd-plugin/
└── __init__.py                     # MODIFIED: added CTFdTeamFlag + cheaters table + /admin/cheaters

controller/
└── import_flags.py                 # MODIFIED: 1 team flag row per challenge (not 50 per-team rows)

tests/
└── load/
    └── k6-ctf-scenario.js          # MODIFIED: 200 VUs, 50 teams, 50s ramp
```

**Structure Decision**: This feature modifies existing infrastructure files in `infra/terraform/`, `k8s/ctfd/`, `ctfd-plugin/`, `controller/`, and `tests/load/`. Two new K8s manifests (`proxysql-deployment.yaml`, `proxysql-configmap.yaml`) are added. `mysql-node-pool.tf` was scaffolded but commented out due to fra1 capacity unavailability.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| CTFd replicas > 2 (now 5) | 200 VUs with 4 workers/replica = 20 connections through ProxySQL; validated stable in Phase 6 testing | Fewer replicas = more workers per pod = higher per-pod memory pressure |
| MySQL memory > 1Gi (now 4Gi) | 2GB InnoDB buffer pool needed for 50-team write throughput; 2Gi request gives headroom above buffer pool | 1Gi caused OOM at 200 VUs in Phase 6 |
| CTFd memory at 2Gi (pre-existing from Phase 6) | 4 Gunicorn workers per replica require ~1.5Gi under load; 512Mi caused worker OOM kills | Already validated in Phase 6 load testing; not a new violation |
| ProxySQL max_connections=25 (server-side) | Caps server-side connections at 25; multiplexes 200+ CTFd client connections; reduces MySQL lock contention | Higher server-side count was not needed at 50-team scale and wastes connection slots |

## Security Changes (discovered during Phase 7 provisioning)

### Cross-Team Flag Submission Vulnerability

**Problem**: CTFd's built-in flag types (`static`, `regex`) have no team identity binding. All flag
rows for a challenge are checked against any submitter. With 50 teams × 3 challenges = 150 static
flag rows, any team could submit another team's flag and score points.

**Fix**: Custom `team` flag type in `ctfd-plugin/__init__.py`:

- `CTFdTeamFlag.compare()` derives the expected flag at validation time:
  `infodays{HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_manifest_id}")[:32]}`
- The submitting team's ID comes from the live CTFd session — not from user input
- Cross-team submission is cryptographically impossible without knowing `CTF_MASTER_SECRET`
- One flag row per challenge (type=`team`, content=`team-derived`, data=manifest ID)
- `import_flags.py` now inserts one row per challenge instead of 50 (one per team)

**Cheating detection**: When a wrong flag matches another team's derived flag:
- A row is inserted into the `cheaters` table with submitting team, owner team, flag, challenge, timestamp
- Detection never crashes flag validation (wrapped in `try/except`)
- Admin endpoint: `GET /admin/cheaters` returns full JSON log (admin-only)

### Missing NetworkPolicy: ProxySQL → MySQL

`allow-proxysql-ingress-mysql` was absent from `k8s/ctfd/networkpolicy.yaml`. The default-deny
posture blocked ProxySQL from reaching MySQL on port 3306. ProxySQL showed all backends as
`SHUNNED`. Fix: added the policy and applied with `kubectl apply -f k8s/ctfd/networkpolicy.yaml`.

### Helm Provider Pattern (cluster provisioning)

Terraform's Helm provider produced "inconsistent final plan" errors and timeouts on fresh clusters.
Established pattern for future re-provisioning:
1. Install Helm charts directly: `helm install ingress-nginx ...` and `helm install cert-manager ...`
2. Import into Terraform state: `terraform import helm_release.ingress_nginx ingress-nginx/ingress-nginx`
3. Continue with `terraform apply` — state matches reality, no recreation attempted
