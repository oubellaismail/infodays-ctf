# Implementation Plan: Cluster & Networking Foundation

**Branch**: `001-cluster-network-foundation` | **Date**: 2026-03-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-cluster-network-foundation/spec.md`

## Summary

Provision the complete DOKS cluster foundation for InfoDays CTF using Terraform.
Deliverables: a 4-node cluster in `fra1`, the three required namespaces with pod
security standards and default-deny network policies, NGINX Ingress, cert-manager
with Let's Encrypt (DNS-01 for wildcard), DOCR with zero-credential-configuration
pull access, and DNS A-records managed from Terraform outputs. All resources are
declared in a single `infra/terraform/` root module; a single `terraform apply`
brings the platform from zero to fully operational.

## Technical Context

**Language/Version**: HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers)
**Primary Dependencies**: Terraform `digitalocean` provider v2.x, `helm` provider v2.x,
`kubernetes` provider v2.x; NGINX Ingress Controller (Helm, ingress-nginx chart);
cert-manager v1.14+ (Helm); DOKS Kubernetes ≥1.28
**Storage**: DigitalOcean Spaces bucket (`infodays-tfstate`) as Terraform remote state
backend — S3-compatible, DigitalOcean-native, no external service required
**Testing**: bash scripts (`tests/`) using `kubectl`, `curl`, and `openssl`
**Target Platform**: DOKS managed cluster, region `fra1`
**Project Type**: Infrastructure as Code (Terraform IaC root module)
**Performance Goals**: Cluster operational ≤15 min from `terraform apply`; trusted
TLS certificate available ≤15 min post-provisioning
**Constraints**: 4× `s-4vcpu-8gb` nodes, `fra1` only; DOCR Starter tier;
DigitalOcean-exclusive (no other cloud provider or external secret manager)
**Scale/Scope**: 1 cluster, 3 namespaces, 4 nodes, single-day event operation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance to Phase 1 | Gate Status |
|---|---|---|
| I. Flag Integrity | Not applicable — no flag logic in Phase 1 | ✅ N/A |
| II. Security-First Pod Isolation | NetworkPolicy default-deny + PodSecurityStandards provisioned here | ✅ PASS |
| III. Pod Lifecycle Discipline | Not applicable — pod lifecycle is Phase 3+ | ✅ N/A |
| IV. DigitalOcean-Exclusive Infrastructure | All resources: DOKS, DOCR, DO DNS, DO Spaces — zero third-party providers | ✅ PASS |
| V. Resource & Cost Discipline | Node pool: 4× `s-4vcpu-8gb`; DOCR Starter; no oversized resources | ✅ PASS |

**Post-design re-check**: All gates pass. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-cluster-network-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── terraform-inputs.md   # Variable definitions and constraints
│   └── terraform-outputs.md  # Output values consumed by other phases
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
infra/
├── terraform/
│   ├── providers.tf          # digitalocean, kubernetes, helm provider config
│   ├── variables.tf          # All input variables with validation
│   ├── outputs.tf            # Cluster endpoint, registry URL, ingress IP, kubeconfig
│   ├── cluster.tf            # DOKS cluster + node pool
│   ├── registry.tf           # DOCR + docker-pull-secret per namespace
│   ├── namespaces.tf         # K8s namespaces + PodSecurity admission labels
│   ├── network-policies.tf   # Default-deny policies + allowlists per namespace
│   ├── ingress.tf            # NGINX Ingress Controller (Helm release)
│   ├── cert-manager.tf       # cert-manager (Helm) + ClusterIssuer + Certificates
│   └── dns.tf                # A-records for ctfd.infodays.net + *.challenges.infodays.net
└── tests/
    ├── validate-cluster.sh           # Reachability + namespace existence
    ├── validate-network-isolation.sh # Challenge pod egress denial tests
    └── validate-tls.sh               # Certificate validity for both domains
```

**Structure Decision**: Single Terraform root module under `infra/terraform/`. All
providers are configured in `providers.tf` using cluster outputs for the `kubernetes`
and `helm` providers. The `tests/` directory contains bash scripts that act as the
acceptance test suite against a live cluster.

## Complexity Tracking

> No constitution violations — table intentionally empty.

---

## Phase 0: Research Findings

*See [research.md](research.md) for full decision log.*

Key decisions resolved:

1. **Terraform state backend**: DigitalOcean Spaces (`infodays-tfstate` bucket,
   `fra1`). Bootstrap step: create bucket before first `terraform init`.
2. **DOKS ↔ DOCR integration**: Use `digitalocean_container_registry_docker_credentials`
   to generate pull credentials, stored as a `kubernetes.io/dockerconfigjson` Secret
   in each namespace (`ctfd`, `challenges`), then bound to the `default` ServiceAccount
   in each namespace. All pods pull from DOCR without per-pod `imagePullSecrets`
   entries. Fully declarative via Terraform.
3. **cert-manager wildcard TLS**: cert-manager v1.x has native (no external webhook)
   DigitalOcean DNS-01 support via `dns01.digitalocean.tokenSecretRef`. Use DNS-01
   for both domains for consistency (avoids mixed solver configuration, simplifies
   ClusterIssuer definition).
4. **DNS A-record timing**: Terraform `kubernetes_service` data source (with
   `wait_for_load_balancer = true`) retrieves the ingress LB IP after the NGINX
   Helm release completes. The `digitalocean_record` resource then depends on that
   data source. Terraform handles the ordering.
5. **Kubernetes minimum version**: DOKS ≥1.28 required. PodSecurityAdmission is GA
   since 1.25; choosing 1.28 ensures stability and aligns with DOKS current LTS
   channel.
6. **Challenge pod outbound internet**: Blocked by default via a dedicated egress
   deny-all NetworkPolicy in the `challenges` namespace. Per-challenge allowlist
   policies are additive and applied in later phases.

---

## Phase 1: Design Artifacts

*Full details in [data-model.md](data-model.md), [contracts/](contracts/), and
[quickstart.md](quickstart.md).*

### Key Design Decisions

**Provider dependency chain**

The `kubernetes` and `helm` Terraform providers require a running cluster to
configure. This is handled by setting their connection attributes from
`digitalocean_kubernetes_cluster.infodays.kube_config[0]` outputs. Terraform
resolves the ordering automatically via the dependency graph.

```
DOCR registry
    ↓
DOKS cluster (+ registry integration)
    ↓
Kubernetes + Helm providers configured
    ↓ (parallel)
├── Namespaces + PodSecurity labels
├── NetworkPolicies (default-deny + ctfd allowlists)
├── NGINX Ingress (Helm)
│       ↓
│   LB IP (kubernetes_service data source)
│       ↓
│   DNS A-records (digitalocean_record)
│       ↓
│   cert-manager (Helm) + ClusterIssuer + Certificates
└── (cert-manager depends on DNS being ready for DNS-01)
```

**NetworkPolicy allowlist matrix**

| Source | Destination | Port | Permitted? |
|---|---|---|---|
| `challenges` pod | `ctfd` namespace | any | ❌ Denied |
| `challenges` pod | peer `challenges` pod | any | ❌ Denied |
| `challenges` pod | K8s API (default/svc) | 443 | ❌ Denied |
| `challenges` pod | 169.254.169.254 | any | ❌ Denied |
| `challenges` pod | internet (0.0.0.0/0) | any | ❌ Denied by default |
| `ctfd` app pod | `ctfd` MySQL pod | 3306 | ✅ Allowlisted |
| `ctfd` app pod | `ctfd` Redis pod | 6379 | ✅ Allowlisted |
| `ctfd` pod | internet (egress) | 443 | ✅ Allowlisted |
| Ingress controller | `ctfd` namespace | 8000 | ✅ Allowlisted |

**PodSecurity namespace labels**

```yaml
challenges:
  pod-security.kubernetes.io/enforce: restricted
  pod-security.kubernetes.io/enforce-version: latest

ctfd:
  pod-security.kubernetes.io/enforce: baseline
  pod-security.kubernetes.io/enforce-version: latest

monitoring:
  # No PSA label in v1 — namespace is empty
```

**cert-manager ClusterIssuer (DNS-01, both domains)**

Single `letsencrypt-prod` ClusterIssuer using DigitalOcean DNS-01 solver.
Two `Certificate` resources: one for `ctfd.infodays.net`, one for
`*.challenges.infodays.net`. Both use the same issuer and solver.

**Terraform state bootstrap (one-time, pre-apply)**

A `spaces-bootstrap/` subdirectory contains a minimal Terraform configuration
(local state) that creates the `infodays-tfstate` Spaces bucket. Operators run
this once before initialising the main module.

```text
infra/
├── spaces-bootstrap/
│   ├── main.tf    # Creates the Spaces bucket only
│   └── README.md
└── terraform/     # Main module (uses the bucket as backend)
```
