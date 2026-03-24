# Implementation Plan: CTFd Platform Stack

**Branch**: `002-ctfd-platform-stack` | **Date**: 2026-03-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-ctfd-platform-stack/spec.md`

## Summary

Deploy CTFd, MySQL 8, and Redis into the `ctfd` namespace as Kubernetes workload manifests, backed by persistent block storage for MySQL. CTFd is exposed via NGINX Ingress with TLS from Let's Encrypt and configured via an idempotent setup script. Team accounts are bulk-created via a Python import script reading a CSV file. Phase 1 already provisioned the namespace, PodSecurityStandards, and baseline network policies; Phase 2 delivers the application layer and fills two missing egress rules (DNS and intra-namespace MySQL/Redis traffic).

## Technical Context

**Language/Version**: HCL (Terraform ≥1.5) for any Terraform additions; YAML (Kubernetes manifests); Bash (setup script); Python 3.11+ (import script)
**Primary Dependencies**: `digitalocean` Terraform provider v2.x (already present); Kubernetes manifest files applied via `kubectl`; CTFd image `ctfd/ctfd:latest`; MySQL 8 image `mysql:8`; Redis 7 image `redis:7-alpine`
**Storage**: MySQL 8 StatefulSet with 10 Gi PVC on `do-block-storage` StorageClass; Redis ephemeral (no PVC)
**Testing**: Bash acceptance tests in `infra/tests/` using `kubectl`, `curl`, `openssl`
**Target Platform**: DOKS cluster in `fra1`; `ctfd` namespace (PodSecurityStandards: `baseline` — already applied by Phase 1)
**Project Type**: Infrastructure / Kubernetes application deployment
**Performance Goals**: Support 50 concurrent teams without degradation; flag submissions recorded within 5 s
**Constraints**: Resource ceilings per constitution — CTFd: 0.5 CPU / 512 Mi; MySQL: 0.5 CPU / 1 Gi; Redis: 0.1 CPU / 256 Mi; 2 CTFd replicas; no node upgrades
**Scale/Scope**: 20–50 teams; 12-hour event window; single MySQL replica (no HA)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I — Flag Integrity | ✅ PASS | `ctfd-secrets` Secret template provided; real values gitignored; `CTF_MASTER_SECRET` reserved for Phase 3 (not used here) |
| II — Security-First Pod Isolation | ✅ PASS | `ctfd` namespace has `baseline` PodSecurityStandards (Phase 1); NetworkPolicy default-deny already applied; CTFd cannot reach `challenges` namespace |
| III — Pod Lifecycle Discipline | N/A | No challenge pods in Phase 2 |
| IV — DO-Exclusive Infrastructure | ⚠️ NOTE | CTFd, MySQL, Redis images pulled from Docker Hub (upstream public images). Constitution targets DOCR for *custom challenge images*; pulling public upstream images from Docker Hub is standard practice and does not conflict with the DOCR requirement for custom images. No remediation needed. |
| V — Resource & Cost Discipline | ✅ PASS | All resource limits match constitution table exactly |
| v1 Scope Boundaries | ✅ PASS | No monitoring, no per-player instances, no on-demand pods introduced |

**Constitution Check Result**: PASS — proceed to Phase 0.

**Phase 1 Re-check (post-design)**:
NetworkPolicy gap filled: two intra-namespace egress rules (MySQL, Redis) and one kube-dns egress rule are added in `k8s/ctfd/networkpolicy.yaml`. These are additive to the Phase 1 default-deny and do not conflict with existing Terraform-managed policies. ✅

## Project Structure

### Documentation (this feature)

```text
specs/002-ctfd-platform-stack/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── setup-ctfd-sh.md
│   └── import-teams-py.md
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
k8s/
└── ctfd/
    ├── deployment.yaml         # CTFd Deployment (2 replicas)
    ├── mysql-statefulset.yaml  # MySQL 8 StatefulSet + PVC
    ├── redis-deployment.yaml   # Redis 7 Deployment
    ├── secrets.yaml            # ctfd-secrets template (gitignored when filled)
    ├── services.yaml           # ClusterIP services: ctfd, mysql, redis
    ├── ingress.yaml            # Ingress → ctfd.infodays.net + TLS
    └── networkpolicy.yaml      # Supplementary egress rules (DNS, MySQL, Redis)

scripts/
├── setup-ctfd.sh               # Idempotent CTFd API configuration script
└── import-teams.py             # Bulk team account creation from CSV

data/
└── teams-template.csv          # CSV template: team_name, email, password

infra/tests/
└── validate-ctfd.sh            # Acceptance tests for Phase 2
```

**Structure Decision**: Hybrid approach — infrastructure lifecycle (cluster, namespaces, ingress controller, cert-manager, DNS, base network policies) stays in `infra/terraform/`. Application workloads (CTFd stack) live in `k8s/ctfd/` as plain Kubernetes manifests applied with `kubectl apply`. This separation allows redeploying just the application without re-running Terraform and is consistent with how the Phase 2 deliverables are specified in `Plan.md`.

## Complexity Tracking

No constitution violations requiring justification.

---

## Phase 0: Research

*See [research.md](research.md)*

## Phase 1: Design

*See [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)*
