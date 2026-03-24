# Feature Specification: Cluster & Networking Foundation

**Feature Branch**: `001-cluster-network-foundation`
**Created**: 2026-03-21
**Status**: Draft
**Input**: Phase 1 — Cluster & Networking Foundation (derived from project constitution)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator Provisions Cluster from Scratch (Priority: P1)

A CTF operator with no existing infrastructure can bring up the entire cluster
foundation — compute, networking, namespaces, ingress, and TLS — by applying a
single declarative configuration. After provisioning, the platform domain
resolves over HTTPS and the namespace structure is in place.

**Why this priority**: Nothing else in the system can be deployed or tested
without the cluster foundation existing. It is the prerequisite for every
subsequent phase.

**Independent Test**: Apply the configuration against an empty DigitalOcean
project, then verify: (a) the cluster is reachable, (b) `https://ctfd.infodays.net`
returns a valid TLS certificate, (c) all three required namespaces exist.

**Acceptance Scenarios**:

1. **Given** an empty DigitalOcean project with valid credentials,
   **When** the operator applies the declarative infrastructure configuration,
   **Then** a running Kubernetes cluster exists in region `fra1` with 4 nodes,
   all three namespaces (`ctfd`, `challenges`, `monitoring`) are present,
   and the ingress controller is running.

2. **Given** a provisioned cluster,
   **When** a browser visits `https://ctfd.infodays.net`,
   **Then** the connection is secured with a trusted TLS certificate issued by
   a public certificate authority — no browser security warning is shown.

3. **Given** a provisioned cluster,
   **When** the operator re-applies the configuration without changes,
   **Then** no resources are recreated or disrupted (idempotent apply).

---

### User Story 2 - Challenge Pods Are Network-Isolated (Priority: P2)

A challenge pod running in the `challenges` namespace cannot initiate
connections to the `ctfd` namespace, to other challenge pods, to the
Kubernetes control plane, or to the cloud infrastructure metadata service.
Isolation is enforced by policy, not by convention.

**Why this priority**: If a challenge is exploited, the attacker MUST NOT be
able to pivot to the scoreboard database, steal flags from other teams, or
access cloud credentials. This boundary is a core security guarantee of the
platform.

**Independent Test**: Deploy a test pod in the `challenges` namespace and
attempt outbound connections to each prohibited destination. All MUST be
denied. Outbound internet is blocked by default; a test pod with an explicit
allowlist policy MUST be able to reach the internet, while one without MUST NOT.

**Acceptance Scenarios**:

1. **Given** a pod running in the `challenges` namespace,
   **When** it attempts to connect to any service in the `ctfd` namespace,
   **Then** the connection is denied — no traffic reaches the destination.

2. **Given** a pod running in the `challenges` namespace,
   **When** it attempts to connect to another pod in the `challenges` namespace,
   **Then** the connection is denied (pods cannot talk to each other).

3. **Given** a pod running in the `challenges` namespace,
   **When** it attempts to reach the cloud metadata endpoint (169.254.169.254),
   **Then** the connection is denied.

4. **Given** a pod running in the `challenges` namespace,
   **When** it attempts to reach the Kubernetes API server,
   **Then** the connection is denied.

5. **Given** a pod running in the `ctfd` namespace,
   **When** it communicates with another service in the `ctfd` namespace
   (e.g., the application to its database),
   **Then** the connection succeeds — explicitly allowlisted intra-namespace
   traffic is permitted.

---

### User Story 3 - Pod Security Standards Are Enforced at Admission (Priority: P3)

Any attempt to schedule a pod that runs as root, uses privileged mode, or
violates the security standard for its namespace is rejected at admission time
— before any workload starts.

**Why this priority**: Enforcement at admission prevents misconfigurations from
ever reaching production. It closes the gap between policy intention and actual
runtime state.

**Independent Test**: Attempt to deploy a pod with root user in the
`challenges` namespace — it MUST be rejected. Deploy an identical pod with
`uid=1000` — it MUST be accepted.

**Acceptance Scenarios**:

1. **Given** the `challenges` namespace has the `restricted` security standard,
   **When** an operator attempts to deploy a pod that runs as root,
   **Then** the admission controller rejects the pod with a clear error message.

2. **Given** the `challenges` namespace,
   **When** an operator deploys a pod with uid=1000 and no elevated
   capabilities,
   **Then** the pod is admitted and runs successfully.

3. **Given** the `ctfd` namespace has the `baseline` security standard,
   **When** an operator deploys CTFd application pods,
   **Then** those pods are admitted (CTFd meets the baseline requirements).

---

### Edge Cases

- What happens if a node fails during the event? Kubernetes automatically
  reschedules affected pods on surviving nodes (best-effort); no operator
  action is required. No uptime SLA is guaranteed — this is acceptable for a
  single-day event.
- What happens if the Cloudflare NS delegation for `ctfd.infodays.net` and
  `challenges.infodays.net` is not in place before provisioning?
  Certificate issuance will fail (cert-manager writes TXT records to DigitalOcean
  but Let's Encrypt can't find them). The NS delegation in Cloudflare and the
  DigitalOcean zones (created by `terraform apply`) must both exist.
- What happens if the operator applies configuration with invalid credentials?
  The apply MUST fail with a clear error — no partial infrastructure state
  should remain.
- What happens if a certificate cannot be issued due to CA rate limits?
  The cluster MUST still be operational; only public HTTPS for the affected
  domain is degraded until the certificate is issued.
- What happens if the operator attempts to deploy a workload to the
  `monitoring` namespace?
  The namespace exists but is intentionally empty in v1; no enforcement
  mechanism blocks deployment, so this is an operator discipline concern
  documented in runbooks.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The infrastructure MUST be fully declarative — no manual console
  clicks or one-off CLI commands are required to reach a running, secure
  cluster.
- **FR-002**: The cluster MUST contain exactly the three namespaces `ctfd`,
  `challenges`, and `monitoring` after provisioning.
- **FR-003**: The `monitoring` namespace MUST be provisioned empty and remain
  empty throughout v1 — no workloads are deployed there.
- **FR-004**: The ingress layer MUST accept external HTTPS traffic and route
  it to services in the `ctfd` namespace by hostname.
- **FR-005**: TLS certificates MUST be automatically provisioned and renewed
  for `ctfd.infodays.net` and `*.challenges.infodays.net` without manual
  operator action after initial provisioning.
- **FR-005a**: DNS A-records for `ctfd.infodays.net` and `*.challenges.infodays.net`
  MUST be created and managed by the infrastructure configuration, using the
  ingress load balancer IP as the record value — no manual DNS step is required
  after provisioning.
- **FR-006**: All namespaces MUST have a default-deny network policy — no
  inter-namespace or intra-namespace traffic is permitted unless explicitly
  allowlisted.
- **FR-007**: Challenge pods MUST be blocked from reaching: the `ctfd`
  namespace, peer challenge pods, the Kubernetes API server, and the cloud
  metadata endpoint (169.254.169.254).
- **FR-007a**: Challenge pods MUST have outbound internet access blocked by
  default. An explicit per-challenge network policy allowlist MAY permit
  outbound internet for specific challenges that require it.
- **FR-008**: The `challenges` namespace MUST enforce the `restricted` pod
  security standard — non-compliant pods are rejected at admission.
- **FR-009**: The `ctfd` namespace MUST enforce the `baseline` pod security
  standard — non-compliant pods are rejected at admission.
- **FR-010**: The infrastructure configuration MUST be idempotent — re-applying
  it against a live cluster produces no resource replacements and no outage.
- **FR-011**: The container image registry MUST be provisioned and accessible
  from within the cluster for pulling challenge images — no manual credential
  configuration is required on cluster nodes.
- **FR-012**: The node pool MUST consist of exactly 4 nodes of the same size
  in region `fra1`.
- **FR-013**: The cluster MUST automatically reschedule pods from a failed node
  onto surviving nodes — no operator intervention is required to restore
  running workloads after a single-node failure.

### Key Entities

- **Cluster**: The managed Kubernetes cluster; attributes include region, node
  count, node size, Kubernetes version.
- **Namespace**: A logical isolation boundary; attributes include name and
  enforced pod security standard level.
- **Network Policy**: A rule set controlling allowed ingress/egress for pods
  in a namespace; attributes include direction, selector, port, and protocol.
- **Ingress**: The external traffic entry point; routes requests by hostname
  to backend services.
- **TLS Certificate**: A certificate bound to one or more hostnames; attributes
  include domain(s), issuer, expiry, and automatic renewal flag.
- **Container Registry**: Image storage and distribution service; attributes
  include access scope and pull credentials available in-cluster.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with valid credentials can bring the cluster from
  zero to fully operational in a single apply run — zero additional manual
  steps required.
- **SC-002**: All three namespaces (`ctfd`, `challenges`, `monitoring`) exist
  and are correctly configured within 15 minutes of provisioning completing.
- **SC-003**: `https://ctfd.infodays.net` serves a valid, browser-trusted TLS
  certificate within 15 minutes of cluster provisioning (allowing for
  certificate issuance time).
- **SC-004**: 100% of connection attempts from a `challenges` pod to any
  prohibited destination are denied — zero successful connections to ctfd
  namespace, peer pods, K8s API, or cloud metadata endpoint.
- **SC-005**: 100% of pod admission attempts that violate the security standard
  for their namespace are rejected — zero non-compliant pods reach Running
  state.
- **SC-006**: Re-applying the infrastructure configuration to a live cluster
  produces zero resource replacements and zero service interruptions.
- **SC-007**: In-cluster image pulls from the container registry succeed on
  all nodes without any manual credential setup post-provisioning.

## Clarifications

### Session 2026-03-21

- Q: Are challenge pods permitted outbound internet access? → A: Blocked by default; individual challenges may be explicitly allowlisted per network policy.
- Q: Are DNS A-records for platform hostnames managed by the infrastructure configuration or set manually? → A: Managed by the infrastructure configuration; records are created automatically from the ingress load balancer IP.
- Q: What is the expected availability behaviour if a cluster node fails during the event? → A: Best-effort continuity; Kubernetes reschedules affected pods automatically on surviving nodes with no operator intervention required.

## Assumptions

- `infodays.net` is on Cloudflare nameservers. Cloudflare NS records delegate
  `ctfd.infodays.net` and `challenges.infodays.net` to DigitalOcean before
  provisioning begins. A-record resolution and certificate issuance both depend
  on this subdomain delegation being in place. The root domain is NOT moved to
  DigitalOcean (it hosts a separate Netlify site).
- The operator holds a DigitalOcean API token with permissions to create
  clusters, registries, and DNS records.
- No conflicting resources (clusters, registries with the same name) exist in
  the target DigitalOcean project.
- Internal `ctfd`-namespace traffic (e.g., app to database) is explicitly
  allowlisted as part of this phase's network policy configuration.
- The `monitoring` namespace is provisioned to reserve the name for v2; no
  enforcement prevents accidental workload deployment there in v1 — operator
  discipline is assumed.
