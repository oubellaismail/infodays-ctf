# Implementation Plan: Network Hardening & Isolation

**Branch**: `005-network-hardening-isolation` | **Date**: 2026-03-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/005-network-hardening-isolation/spec.md`

## Summary

Harden the InfoDays CTF cluster so that a challenge pod with RCE cannot reach other teams, the CTFd platform, the Kubernetes API, or the cloud metadata service. The phase closes three open gaps against existing Phase 1–4 work: (1) scope the ctfd namespace's external HTTPS egress to controller pods only, (2) complete the RBAC Role verbs for the challenge-controller service account and add the missing challenge-daemon service account and Role, and (3) deliver a standalone verification test suite. Pod Security Standards and most network policies are already applied via Terraform.

## Technical Context

**Language/Version**: YAML (Kubernetes manifests), Bash 5 (test runner)
**Primary Dependencies**: Kubernetes NetworkPolicy API, PSS admission controller (built-in), RBAC API (built-in), Cilium CNI (DOKS), `kubectl`
**Storage**: N/A
**Testing**: `bash scripts/run-isolation-tests.sh` (connection-attempt pods + kubectl auth can-i checks)
**Target Platform**: DOKS (DigitalOcean Kubernetes Service), fra1, Kubernetes 1.29+
**Project Type**: Infrastructure configuration (YAML manifests + Terraform HCL)
**Performance Goals**: Full isolation test suite completes in under 60 seconds (5 s timeout × 4 test pods + overhead)
**Constraints**: NetworkPolicy is additive/allowlist; blocking is achieved by absence of allow rules under default-deny baseline
**Scale/Scope**: 2 namespaces (challenges, ctfd); 4 network-isolation test cases; 2 service accounts; ~12 YAML manifests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Flag Integrity | ✅ PASS | No flag derivation or Secret changes in this phase |
| II. Security-First Pod Isolation | ✅ PASS | This phase *implements* the isolation requirement — PSS restricted/baseline, NetworkPolicy default-deny, all four blocked destinations (ctfd namespace, cross-pod, K8s API, DO metadata) |
| III. Pod Lifecycle Discipline | ✅ PASS | No lifecycle changes; daemon RBAC scoped to patch/update only (no delete) |
| IV. DigitalOcean-Exclusive Infrastructure | ✅ PASS | YAML manifests only; no external cloud resources |
| V. Resource & Cost Discipline | ✅ PASS | Test pods are ephemeral, minimal resources |

**Post-design re-check**: All five principles remain PASS — see data-model.md for resource specifications.

## Project Structure

### Documentation (this feature)

```text
specs/005-network-hardening-isolation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── rbac-permissions.md
│   └── network-policy-allowlist.md
└── tasks.md             # Phase 2 output (not created here)
```

### Source Code (repository root)

```text
infra/terraform/
└── network-policies.tf          # UPDATE: scope allow-ctfd-egress-internet to controller pods

k8s/
├── network-policies/            # NEW: standalone YAML equivalents of Terraform policies
│   ├── challenges-default-deny.yaml
│   ├── challenges-allow-ingress.yaml
│   ├── challenges-allow-dns.yaml
│   ├── ctfd-default-deny.yaml
│   ├── ctfd-allow-internal.yaml
│   └── ctfd-allow-controller-egress.yaml
├── pod-security/                # NEW: kubectl-applicable PSS namespace labels
│   └── namespace-labels.yaml
└── rbac/                        # NEW: complete RBAC for controller + daemon
    ├── challenge-controller-rbac.yaml
    └── challenge-daemon-rbac.yaml

tests/
└── network-isolation/           # NEW: isolation test pod manifests
    ├── test-deny-ctfd.yaml
    ├── test-deny-cross-team.yaml
    ├── test-deny-kube-api.yaml
    └── test-deny-metadata.yaml

scripts/
└── run-isolation-tests.sh       # NEW: test runner (apply → wait → PASS/FAIL → cleanup)
```

**Structure Decision**: Existing Terraform in `infra/terraform/network-policies.tf` manages default-deny and the main allowlist via IaC. The `k8s/network-policies/` YAML files provide standalone kubectl-applicable equivalents for manual recovery and CI verification. RBAC moves from `k8s/controller/rbac.yaml` to `k8s/rbac/` with two separate files (controller and daemon). The existing `k8s/controller/rbac.yaml` should be superseded by `k8s/rbac/challenge-controller-rbac.yaml` after this phase.

## Gap Analysis (Existing → Required)

| Area | Current State | Gap | Action |
|------|--------------|-----|--------|
| `allow-ctfd-egress-internet` (Terraform) | Allows ALL ctfd pods → 0.0.0.0/0:443 | Should be controller pods only (Q1 clarification) | Update Terraform pod_selector |
| Controller RBAC verbs | get, list, create, patch on Deployments; create only on Secrets/Services/Ingresses | Missing: update, delete, watch; missing: get/list on Secrets/Services/Ingresses | Replace Role in `k8s/rbac/challenge-controller-rbac.yaml` |
| Daemon ServiceAccount | Does not exist | Entire daemon identity and permissions are missing | Create SA + Role + RoleBinding in `k8s/rbac/challenge-daemon-rbac.yaml` |
| PSS labels | Applied via Terraform (`namespaces.tf`) — challenges: restricted, ctfd: baseline | No standalone YAML for kubectl-only apply | Create `k8s/pod-security/namespace-labels.yaml` |
| Network policy YAMLs | Terraform HCL only in `infra/terraform/network-policies.tf` | No standalone YAML files for manual recovery | Create `k8s/network-policies/` files |
| Isolation test suite | Does not exist | FR-022/FR-023 entirely unimplemented | Create 4 test pods + `scripts/run-isolation-tests.sh` |

## Complexity Tracking

No constitution violations. Complexity tracking table not applicable.
