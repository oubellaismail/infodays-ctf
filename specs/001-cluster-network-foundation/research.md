# Research: Cluster & Networking Foundation

**Feature**: 001-cluster-network-foundation
**Date**: 2026-03-21

This document records decisions resolved during Phase 0. Each entry follows the
Decision / Rationale / Alternatives format.

---

## 1. Terraform State Backend

**Decision**: DigitalOcean Spaces (`infodays-tfstate` bucket, `fra1`), using
the S3-compatible backend configuration.

**Rationale**: Spaces is DigitalOcean-native (constitution: DigitalOcean-only),
S3-compatible (Terraform has first-class support via the `s3` backend type with
a custom endpoint), and free at the scale of a single-team CTF project. State
is stored remotely, enabling team members to share it without passing files and
protecting against local machine loss.

**Alternatives considered**:
- **Local state**: Simplest, but lost if the operator's machine fails before
  teardown. Unacceptable for shared infrastructure.
- **Terraform Cloud**: External service; violates the DigitalOcean-only
  constraint in spirit.
- **GitOps (state in git)**: State files contain sensitive data (kubeconfig
  values); committing them to git is a security violation.

**Backend configuration snippet** (for reference):
```hcl
terraform {
  backend "s3" {
    endpoints = {
      s3 = "https://fra1.digitaloceanspaces.com"
    }
    bucket                      = "infodays-tfstate"
    key                         = "cluster/terraform.tfstate"
    region                      = "us-east-1"   # placeholder required by S3 backend
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    use_path_style              = true
  }
}
```

**Note**: `endpoint` and `force_path_style` are deprecated in Terraform ≥1.5's
S3 backend. Use `endpoints.s3` and `use_path_style` instead. Also add
`skip_requesting_account_id = true` to prevent the backend from calling AWS
STS/IAM (which DigitalOcean Spaces does not support).

**Spaces credentials** are supplied as environment variables (not Terraform
variables) — the S3 backend cannot use variable interpolation:
```bash
export AWS_ACCESS_KEY_ID="<spaces-access-key>"
export AWS_SECRET_ACCESS_KEY="<spaces-secret-key>"
```

---

## 2. DOKS ↔ DOCR Zero-Credential Integration

**Decision**: Use the `digitalocean_container_registry_docker_credentials`
Terraform resource to generate Docker credentials, store them as a Kubernetes
`imagePullSecret` in each namespace that needs registry access, and bind the
secret to the `default` ServiceAccount in those namespaces. This is fully
declarative and satisfies FR-011.

**Rationale**: The `digitalocean_kubernetes_cluster` Terraform resource does
not have a built-in `registry_integration` attribute for automatic DOCR
authentication. The confirmed Terraform pattern is:
1. Provision DOCR with `digitalocean_container_registry`.
2. Generate credentials with `digitalocean_container_registry_docker_credentials`
   (outputs a Docker config JSON).
3. Create a Kubernetes Secret of type `kubernetes.io/dockerconfigjson` in each
   target namespace using the credentials output.
4. Patch the `default` ServiceAccount in each namespace to reference the pull
   secret — all pods using the default service account then pull from DOCR
   without any per-pod `imagePullSecrets` entry.

This is fully declarative (FR-001), idempotent (FR-010), and requires zero
manual operator steps after `terraform apply` (FR-011).

**Terraform pattern**:
```hcl
resource "digitalocean_container_registry_docker_credentials" "infodays" {
  registry_name = digitalocean_container_registry.infodays.name
  write         = false   # pull-only for cluster nodes
}

resource "kubernetes_secret" "docr_pull_secret" {
  for_each = toset(["ctfd", "challenges"])

  metadata {
    name      = "docr-pull-secret"
    namespace = each.key
  }

  type = "kubernetes.io/dockerconfigjson"
  data = {
    ".dockerconfigjson" = digitalocean_container_registry_docker_credentials.infodays.docker_credentials
  }
}

resource "kubernetes_default_service_account" "patch_pull_secret" {
  for_each = toset(["ctfd", "challenges"])

  metadata { namespace = each.key }

  image_pull_secret { name = "docr-pull-secret" }
}
```

**Alternatives considered**:
- **`registry_integration` attribute on `digitalocean_kubernetes_cluster`**:
  Not available in the Terraform provider; would require the `doctl` CLI
  command `kubernetes cluster registry configure` — a manual, non-declarative
  step ruled out by the constitution.
- **Per-pod `imagePullSecrets`**: Works but requires every pod spec to
  reference the secret explicitly. Error-prone and not zero-configuration
  from the operator's perspective.
- **Manual `docker login` on nodes**: Not declarative; violates FR-001.

---

## 3. cert-manager Wildcard TLS — DNS-01 Challenge

**Decision**: Use cert-manager's native DigitalOcean DNS-01 solver for both
certificates (`ctfd.infodays.net` and `*.challenges.infodays.net`). A single
`letsencrypt-prod` ClusterIssuer handles both.

**Rationale**:
- `*.challenges.infodays.net` is a wildcard — Let's Encrypt REQUIRES DNS-01
  for wildcard certificates. HTTP-01 cannot issue wildcards.
- cert-manager v1.x has built-in (no external webhook) support for
  DigitalOcean DNS-01 via the `dns01.digitalocean` solver type, using a
  Kubernetes Secret that holds the DO API token.
- Using DNS-01 for `ctfd.infodays.net` as well (rather than HTTP-01) avoids a
  mixed-solver ClusterIssuer and simplifies the configuration to a single
  solver definition.

**cert-manager ClusterIssuer snippet**:
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@infodays.net
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        digitalocean:
          tokenSecretRef:
            name: do-dns-token
            key: access-token
```

**Alternatives considered**:
- **HTTP-01 for `ctfd.infodays.net`, DNS-01 for wildcard**: Technically works
  but requires two solver types in the ClusterIssuer, increasing complexity
  for minimal benefit.
- **External webhook (cert-manager-webhook-digitalocean)**: An older approach
  before cert-manager added native DO support. No longer needed for cert-manager
  v1.x.
- **Manual certificate + Kubernetes Secret**: Not automated; violates FR-005
  (automatic renewal required).
- **Cloudflare proxy for TLS termination**: Explicitly prohibited by constitution.

---

## 4. DNS A-Record Management in Terraform

**Decision**: Use a `kubernetes_service` data source with
`wait_for_load_balancer = true` to retrieve the NGINX Ingress load balancer IP
after the Helm release deploys, then create `digitalocean_record` resources
pointing to that IP.

**Rationale**: The LB IP is assigned by DigitalOcean after the `ingress-nginx`
service of type `LoadBalancer` is created. Terraform's `kubernetes_service`
data source can block until the LB IP is available. Using a data source (rather
than a hard-coded IP) keeps the configuration fully dynamic — no manual IP
lookup step.

**Terraform pattern**:

Because `infodays.net` is not managed by DigitalOcean, DNS zones for the two
CTF subdomains are created as separate DigitalOcean domain resources. Cloudflare
NS records delegate these subdomains to DigitalOcean (see research section 3a).

```hcl
resource "digitalocean_domain" "ctfd" {
  name = "ctfd.infodays.net"
}

resource "digitalocean_domain" "challenges" {
  name = "challenges.infodays.net"
}

data "kubernetes_service" "ingress_nginx_lb" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }
  depends_on = [helm_release.ingress_nginx]
}

resource "digitalocean_record" "ctfd_a" {
  domain = digitalocean_domain.ctfd.name
  type   = "A"
  name   = "@"
  value  = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300
}

resource "digitalocean_record" "challenges_wildcard_a" {
  domain = digitalocean_domain.challenges.name
  type   = "A"
  name   = "*"
  value  = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300
}
```

**Alternatives considered**:
- **Manual DNS after apply**: Operator looks up LB IP and sets DNS manually.
  Breaks the "single apply → operational" user story (SC-001). Ruled out.
- **DigitalOcean external-dns controller**: Kubernetes controller that
  auto-creates DNS records from Ingress annotations. More automated for
  multi-tenant scenarios but adds an extra controller and is over-engineered
  for a single-event CTF.

---

## 5. Kubernetes Minimum Version

**Decision**: Use `data.digitalocean_kubernetes_versions` with no version prefix
to always resolve to the latest available DOKS version.

**Rationale**:
- The originally planned `1.28` prefix is no longer available on DOKS (DigitalOcean
  retired it). Pinning to a specific minor version causes `terraform apply` to
  fail with "Missing required argument" (the data source returns null for unknown
  prefixes).
- PodSecurityAdmission (PSA) is GA since K8s 1.25 — any current DOKS version
  satisfies this requirement.
- `auto_upgrade = false` is set on the cluster to prevent disruptive upgrades
  during the event regardless of which version is provisioned.
- The cluster was deployed at `1.35.1-do.0` in practice.

**Alternatives considered**:
- **Pin to `1.31` or `1.32`**: Works today but will break again when DOKS
  retires that minor version. Latest-always is more resilient for a periodically
  re-provisioned event cluster.
- **Hard-code version string**: Same fragility problem as pinning a minor version.

---

## 3a. DNS Architecture — Cloudflare + Subdomain NS Delegation

**Decision**: Keep `infodays.net` on Cloudflare nameservers. Delegate only
`ctfd.infodays.net` and `challenges.infodays.net` to DigitalOcean via NS
records in Cloudflare. cert-manager continues using the DigitalOcean DNS-01
solver unchanged.

**Rationale**:
- The root domain `infodays.net` hosts a separate Netlify site and must stay on
  Cloudflare. Moving it to DigitalOcean would break the Netlify setup.
- Namecheap BasicDNS (the previous registrar DNS) does not correctly serve
  subdomain NS delegation records — records added there did not propagate
  globally. Cloudflare propagates NS records to 200+ data centers in under 30s.
- cert-manager writes ACME DNS-01 TXT records to DigitalOcean via the DO API.
  Let's Encrypt queries the authoritative nameserver for the domain. With
  Cloudflare delegating the subdomains to DigitalOcean, Let's Encrypt follows
  the delegation chain and finds the TXT records in DigitalOcean. No code changes
  to cert-manager are required.
- **Chicken-and-egg**: The Cloudflare NS records can be added before or after
  `terraform apply`. However, DigitalOcean must have the zones created (by
  `terraform apply`) for queries to DigitalOcean's nameservers to resolve.

**Cloudflare NS records** (proxy status: DNS only / grey cloud):

| Type | Name | Value |
|------|------|-------|
| NS | `ctfd` | `ns1.digitalocean.com` |
| NS | `ctfd` | `ns2.digitalocean.com` |
| NS | `ctfd` | `ns3.digitalocean.com` |
| NS | `challenges` | `ns1.digitalocean.com` |
| NS | `challenges` | `ns2.digitalocean.com` |
| NS | `challenges` | `ns3.digitalocean.com` |

**Alternatives considered**:
- **Move `infodays.net` fully to DigitalOcean**: Requires re-creating all
  Netlify records in DigitalOcean and loses the Cloudflare DDoS/CDN layer for
  the root domain. Risk not justified for this change.
- **NS1 webhook for cert-manager**: Requires deploying an additional Helm chart
  and a new API key secret. Over-engineered for a CTF event.
- **HTTP-01 challenge instead of DNS-01**: Cannot issue wildcard certificates.
  `*.challenges.infodays.net` requires DNS-01. Not viable.
- **Namecheap BasicDNS subdomain NS delegation**: Attempted and confirmed broken
  — records were added but did not propagate (all red on dnschecker.org).

## 6. NetworkPolicy — Default-Deny + Challenge Egress

**Decision**: Apply a `default-deny-all` NetworkPolicy to every namespace (both
ingress and egress). Add explicit allowlist policies for known-good flows in
`ctfd`. Challenge pod outbound internet is blocked by default; per-challenge
additive policies are applied in Phase 3+.

**Rationale**:
- Default-deny is the only posture that satisfies FR-006 and FR-007
  unambiguously. Any other approach requires reasoning about what is implicitly
  permitted, which is error-prone in a CTF context where the attack surface is
  maximally adversarial.
- Blocking challenge pod internet by default (clarification Q1 resolution)
  prevents data exfiltration and payload downloads from exploited pods.
  Per-challenge opt-in is additive and explicit.

**Alternatives considered**:
- **Default-allow with deny rules for specific destinations**: Simpler to
  configure but fragile — a missed destination creates an exploit path.
- **Calico/Cilium for richer policy**: More expressive policies but adds
  a CNI dependency. DOKS ships with a default CNI that supports standard
  K8s NetworkPolicy. No third-party CNI needed for this use case.

---

## 7. PodSecurityAdmission vs. OPA/Gatekeeper

**Decision**: Use Kubernetes native PodSecurityAdmission (PSA) labels on
namespaces. No external admission webhook (OPA, Gatekeeper, Kyverno) is
required.

**Rationale**:
- PSA is built into Kubernetes since 1.25 — zero additional components to
  install, configure, or maintain.
- The `restricted` and `baseline` standards cover all requirements stated in
  FR-008 and FR-009.
- For a single-day event with a small team, PSA provides sufficient coverage
  without the operational overhead of an external admission controller.

**Alternatives considered**:
- **Kyverno or OPA/Gatekeeper**: More expressive policy (custom rules). Not
  needed for the standard security levels required here. Adds complexity.
- **No pod security enforcement**: Never acceptable per constitution Principle II.
