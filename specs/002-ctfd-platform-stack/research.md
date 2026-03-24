# Research: CTFd Platform Stack

**Branch**: `002-ctfd-platform-stack` | **Date**: 2026-03-24

## Decision Log

### D-001: Manifest Delivery — Hybrid Terraform + kubectl

**Decision**: Use plain Kubernetes YAML manifests in `k8s/ctfd/` applied with `kubectl apply`, not via the Terraform `kubernetes_manifest` resource.

**Rationale**: Phase 1 Terraform owns the infrastructure layer (cluster, namespaces, PodSecurityStandards, network policy defaults, ingress controller, cert-manager, DNS). Application workloads (CTFd, MySQL, Redis) have a different lifecycle — they may be restarted, reconfigured, or torn down independently without changing cluster infrastructure. Separating them avoids a Terraform state dependency on live application pods and simplifies `terraform destroy` during event teardown.

**Alternatives considered**:
- Pure Terraform with `kubernetes_manifest` resource: rejected because it couples application redeploy to Terraform state and complicates destruction.
- Helm chart for CTFd: rejected because it adds a dependency for a stack that is fully custom-configured and small enough to manage directly.

---

### D-002: CTFd Docker Image Source

**Decision**: Pull `ctfd/ctfd:latest` from Docker Hub (public registry). MySQL and Redis also pulled from Docker Hub.

**Rationale**: The constitution's DOCR requirement targets *custom challenge images* built by the event team. Upstream open-source images (CTFd, MySQL, Redis) are standard public images with no custom content. Mirroring them to DOCR would add friction with no security benefit.

**Alternatives considered**:
- Mirror all images to DOCR: rejected as unnecessary operational overhead for public third-party images.
- Pin to specific digest: deferred — `latest` is acceptable for a short-lived event environment; pinning can be added in Phase 6 hardening.

---

### D-003: NetworkPolicy Gap — Missing CTFd Egress Rules

**Decision**: Phase 2 adds `k8s/ctfd/networkpolicy.yaml` with three supplementary policies that fill gaps left by Phase 1.

**Rationale**: Phase 1 Terraform added default-deny-all plus ingress-side allow rules (MySQL ingress, Redis ingress, ingress-nginx ingress). CTFd pods have no egress policies for intra-namespace traffic to MySQL/Redis, and no DNS egress. Without these, CTFd pods cannot resolve hostnames or connect to MySQL/Redis despite the ingress-side allows.

**Gaps filled by Phase 2**:
1. `allow-ctfd-egress-mysql` — CTFd pods egress to MySQL Service on TCP 3306 within `ctfd` namespace.
2. `allow-ctfd-egress-redis` — CTFd pods egress to Redis Service on TCP 6379 within `ctfd` namespace.
3. `allow-ctfd-egress-dns` — All pods in `ctfd` namespace egress to `kube-system` namespace on UDP/TCP 53 (kube-dns).

**Note**: The existing `allow-ctfd-egress-internet` policy (port 443 to 0.0.0.0/0) from Phase 1 covers ACME validation and any optional external HTTPS calls. SMTP egress (ports 587/465) is not added; if mail is required, an operator must add an additional NetworkPolicy at event time.

---

### D-004: MySQL vs PostgreSQL

**Decision**: MySQL 8. No alternative considered.

**Rationale**: Explicitly specified in Plan.md. CTFd supports both MySQL and PostgreSQL; MySQL 8 is the default and most-tested configuration for CTFd deployments.

---

### D-005: CTFd Readiness — Init Container Strategy

**Decision**: Use a `busybox` init container running `until nc -z mysql 3306; do sleep 2; done` before CTFd starts.

**Rationale**: CTFd will crash-loop if the MySQL service is not reachable on startup. The init container gate prevents the main container from starting until MySQL accepts connections, giving clean startup sequencing without relying solely on Kubernetes restart backoff.

**Alternatives considered**:
- Kubernetes `startupProbe` only: insufficient — it tests CTFd's own endpoint, not the MySQL dependency.
- `wait-for-it.sh` script: functionally identical; `nc` in busybox is simpler with no extra file needed.

---

### D-006: Redis Authentication

**Decision**: No Redis password. Redis accessible only within the `ctfd` namespace via NetworkPolicy.

**Rationale**: Redis is a purely intra-namespace service protected by default-deny NetworkPolicy. No external access path exists. Adding a password creates a credential management burden (another Secret value) with no meaningful security gain given network isolation.

**Alternatives considered**:
- Redis with `requirepass`: rejected for the reasons above; can be added as a hardening step in Phase 6 if desired.

---

### D-007: Secret Template Gitignore Strategy

**Decision**: `k8s/ctfd/secrets.yaml` is committed as a template with placeholder values. A `.gitignore` rule MUST exclude any file matching `k8s/ctfd/secrets.yaml` that contains real values, or the operator uses a separate file (e.g., `k8s/ctfd/secrets.local.yaml`) for actual values.

**Rationale**: Constitution Principle I mandates that K8s Secret manifests containing real values are gitignored. The template (with placeholder strings) is safe to commit and helps operators understand the required structure.

**Implementation**: Add `k8s/ctfd/secrets.local.yaml` to `.gitignore`. Template uses `CHANGE_ME` placeholders. Operators copy to `secrets.local.yaml` and fill real values before applying.

---

### D-008: CTFd Ingress Port

**Decision**: CTFd Service exposes port 8000 (CTFd's internal HTTP port), not port 80.

**Rationale**: The existing Phase 1 NetworkPolicy `allow-ingress-to-ctfd` already opens port 8000 from the ingress-nginx namespace. CTFd runs its Gunicorn worker on port 8000 by default. The Service maps `port: 80 → targetPort: 8000` for clarity.

---

### D-009: Acceptance Test Scope

**Decision**: `infra/tests/validate-ctfd.sh` covers: TLS certificate validity, HTTP 200 response at `https://ctfd.infodays.net`, CTFd login page presence, MySQL data persistence across pod restart, and NetworkPolicy block test (CTFd → challenges namespace).

**Rationale**: Matches the Definition of Done from Plan.md exactly. Load testing (50 concurrent teams) is deferred to Phase 6 event readiness.
