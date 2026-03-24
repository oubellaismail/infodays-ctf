# Data Model: Cluster & Networking Foundation

**Feature**: 001-cluster-network-foundation
**Date**: 2026-03-21

This document describes the infrastructure entities managed by the Terraform
root module. Entities map directly to Terraform resources or data sources.

---

## Entities

### SpacesBackendBucket

Bootstrap entity (managed in `spaces-bootstrap/`). Created once before the
main module is initialised.

| Attribute | Value / Constraint |
|---|---|
| `name` | `infodays-tfstate` |
| `region` | `fra1` |
| `acl` | `private` |
| `versioning` | enabled |

**Lifecycle**: Created once; never destroyed while any Terraform state exists.

---

### ContainerRegistry

| Attribute | Value / Constraint |
|---|---|
| `name` | `infodays-registry` |
| `subscription_tier_slug` | `starter` (constitution maximum) |
| `region` | `fra1` |

**Relationships**: Pull credentials generated via
`digitalocean_container_registry_docker_credentials` and stored as K8s Secrets
in `ctfd` and `challenges` namespaces; bound to the `default` ServiceAccount
in each namespace.

**Constraint**: DOCR Starter tier MUST NOT be upgraded without a constitution
amendment.

---

### Cluster

| Attribute | Value / Constraint |
|---|---|
| `name` | `infodays-ctf` |
| `region` | `fra1` (fixed) |
| `version` | DOKS channel `1.28` or latest patch in that minor |
| `registry_integration` | N/A — pull credentials managed via `DockerPullSecret` entity |
| `auto_upgrade` | `false` (event cluster — stability over patches) |
| `surge_upgrade` | `false` |
| `ha` | `false` (cost constraint; best-effort availability accepted) |

**Lifecycle**: Provisioned before event; destroyed after event teardown.

---

### NodePool

Owned by `Cluster` (one pool per cluster in this configuration).

| Attribute | Value / Constraint |
|---|---|
| `name` | `infodays-workers` |
| `size` | `s-4vcpu-8gb` (constitution maximum; MUST NOT exceed) |
| `node_count` | `4` (fixed; MUST NOT exceed 5 per constitution) |
| `auto_scale` | `false` |
| `labels` | `role=worker` |

**Constraint**: `node_count` MUST NOT be set above 4. `size` MUST NOT exceed
`s-4vcpu-8gb`.

---

### Namespace

Three instances; attributes differ by name and security policy.

| Namespace | `pod_security_enforce` | `pod_security_version` | Workloads |
|---|---|---|---|
| `ctfd` | `baseline` | `latest` | CTFd app, MySQL, Redis, controller API, lifetime daemon |
| `challenges` | `restricted` | `latest` | Challenge pods only |
| `monitoring` | *(none in v1)* | *(none in v1)* | Empty — reserved for v2 |

**Labels applied** (K8s admission):
```
pod-security.kubernetes.io/enforce: <level>
pod-security.kubernetes.io/enforce-version: latest
pod-security.kubernetes.io/warn: <level>
pod-security.kubernetes.io/warn-version: latest
```

**Lifecycle**: Created at provisioning; MUST NOT be renamed or deleted until
end-of-event teardown.

---

### NetworkPolicy

One default-deny policy per namespace, plus explicit allowlist policies for
permitted flows. Allowlist policies are named by the flow they permit.

#### Default-deny policies (all three namespaces)

| Policy name | Namespace | Effect |
|---|---|---|
| `default-deny-all` | `ctfd` | Denies all ingress and egress unless overridden |
| `default-deny-all` | `challenges` | Denies all ingress and egress unless overridden |
| `default-deny-all` | `monitoring` | Denies all ingress and egress (empty namespace) |

#### Allowlist policies (`ctfd` namespace)

| Policy name | Direction | Source / Destination | Ports |
|---|---|---|---|
| `allow-ctfd-mysql` | ingress to MySQL | from CTFd app pod | 3306 |
| `allow-ctfd-redis` | ingress to Redis | from CTFd app pod | 6379 |
| `allow-ctfd-egress-internet` | egress from CTFd | to 0.0.0.0/0 | 443 |
| `allow-ingress-to-ctfd` | ingress to CTFd app | from ingress-nginx namespace | 8000 |

#### Allowlist policies (`challenges` namespace)

| Policy name | Direction | Description |
|---|---|---|
| *(none in Phase 1)* | — | Per-challenge allowlists added in later phases |

**Note**: The `challenges` default-deny policy blocks outbound internet by
default. Per-challenge additive policies are defined in Phase 3+ (challenge
deployment phase).

---

### DockerPullSecret

Kubernetes Secret of type `kubernetes.io/dockerconfigjson`, provisioned in
each namespace that pulls challenge images.

| Attribute | Value / Constraint |
|---|---|
| `name` | `docr-pull-secret` |
| `namespaces` | `ctfd`, `challenges` |
| `type` | `kubernetes.io/dockerconfigjson` |
| `data source` | `digitalocean_container_registry_docker_credentials` (pull-only) |
| `bound to` | `default` ServiceAccount in each namespace |

**Lifecycle**: Created at provisioning time by Terraform; rotated by re-applying
when credentials expire (DigitalOcean credentials expire after 30 days unless
`expiry_seconds` is set to 0 for non-expiring).

**Constraint**: The credentials are pull-only (`write = false`). No namespace
should have push access from within the cluster.

---

### HelmRelease — NGINX Ingress Controller

| Attribute | Value |
|---|---|
| `chart` | `ingress-nginx/ingress-nginx` |
| `namespace` | `ingress-nginx` (own namespace, not `ctfd`) |
| `service.type` | `LoadBalancer` (DigitalOcean LB) |
| `controller.replicaCount` | `1` (event cluster; not HA) |

**Outputs**: `status.loadBalancer.ingress[0].ip` — used as DNS A-record value.

---

### HelmRelease — cert-manager

| Attribute | Value |
|---|---|
| `chart` | `cert-manager/cert-manager` |
| `version` | `v1.14.x` or latest stable |
| `namespace` | `cert-manager` |
| `installCRDs` | `true` |

---

### ClusterIssuer

Single issuer for all certificates.

| Attribute | Value |
|---|---|
| `name` | `letsencrypt-prod` |
| `server` | `https://acme-v02.api.letsencrypt.org/directory` |
| `solver` | `dns01` via DigitalOcean (`dns01.digitalocean.tokenSecretRef`) |
| `DO token secret` | K8s Secret `do-dns-token` in `cert-manager` namespace |

**Constraint**: `CTF_MASTER_SECRET` is separate from the DO API token. The DO
token used here is for DNS management only, scoped to the minimum required
permissions.

---

### Certificate

Two instances; both use the `letsencrypt-prod` ClusterIssuer.

| Certificate name | `dnsNames` | Namespace | Secret name |
|---|---|---|---|
| `ctfd-tls` | `ctfd.infodays.net` | `ctfd` | `ctfd-tls-secret` |
| `challenges-wildcard-tls` | `*.challenges.infodays.net` | `ingress-nginx` | `challenges-tls-secret` |

**Lifecycle**: Automatically renewed by cert-manager before expiry (Let's
Encrypt 90-day certs; renewed at 60 days).

---

### DNSRecord

Two A-records, both pointing to the NGINX Ingress load balancer IP.

| Record | Type | Value | TTL |
|---|---|---|---|
| `ctfd.infodays.net` | `A` | ingress LB IP (Terraform output) | 300 |
| `*.challenges.infodays.net` | `A` | ingress LB IP (Terraform output) | 300 |

**Dependency**: Created after `kubernetes_service` data source confirms the LB
IP is assigned.

---

## State Transitions

### Cluster lifecycle

```
[not created] → terraform apply → [Running]
[Running]      → event end       → terraform destroy → [destroyed]
```

### Certificate lifecycle

```
[not issued] → cert-manager ACME DNS-01 → [Issued] → auto-renew at 60d → [Issued]
[Issued]     → cert-manager failure      → [Errored] → retry            → [Issued]
```

### NetworkPolicy enforcement

NetworkPolicies are declarative and stateless from a lifecycle perspective.
They are applied at namespace creation time and remain unchanged until
end-of-event teardown.
