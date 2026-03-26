# Feature Specification: Network Hardening & Isolation

**Feature Branch**: `005-network-hardening-isolation`
**Created**: 2026-03-26
**Status**: Implemented
**Input**: User description: "Network Hardening & Isolation for InfoDays CTF — enforce complete network isolation and pod security so a player with RCE inside a challenge pod cannot reach other teams, CTFd internals, or the Kubernetes API."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Challenge Sandbox Isolation (Priority: P1)

A CTF player who achieves remote code execution inside a challenge pod must be completely contained. They cannot communicate with other teams' pods, reach the CTFd platform, access the Kubernetes API, or query the cloud provider metadata service. The compromise stops at the boundary of their single challenge pod.

**Why this priority**: This is the core safety requirement of the entire event. Without isolation, one attacker with RCE can steal other teams' flags, manipulate scoreboards, or take over the cluster. Every other phase assumes this boundary holds.

**Independent Test**: Deploy a single challenge pod, then run a dedicated isolation test suite from within it. Verify that all outbound connections to forbidden destinations are blocked. This delivers the core security guarantee even without the full RBAC or pod security hardening.

**Acceptance Scenarios**:

1. **Given** a challenge pod is running in the `challenges` namespace, **When** a process inside it attempts to connect to another team's challenge service, **Then** the connection times out or is refused with no data exchanged.
2. **Given** a challenge pod is running, **When** a process inside it attempts to connect to the CTFd platform URL, **Then** the connection is blocked before any HTTP request is sent.
3. **Given** a challenge pod is running, **When** a process inside it attempts to reach the Kubernetes API endpoint, **Then** the connection is refused and no cluster data is returned.
4. **Given** a challenge pod is running, **When** a process inside it queries the cloud provider metadata service, **Then** the connection is blocked and no credentials are returned.
5. **Given** a challenge pod needs to resolve hostnames, **When** it makes a DNS lookup, **Then** DNS resolution succeeds (DNS egress is permitted).

---

### User Story 2 - CTFd Namespace Internal Isolation (Priority: P2)

The CTFd platform, database, and controller components communicate only with each other over predefined internal paths. No external traffic reaches the database or Redis cache directly. The controller can only talk to the `challenges` namespace to manage pods — not to external services or other namespaces it shouldn't touch.

**Why this priority**: A compromise of the CTFd web interface should not give an attacker direct database access. The controller's ability to manage Kubernetes resources must be scoped narrowly to prevent lateral movement.

**Independent Test**: Apply only the `ctfd` namespace network policies (without the `challenges` policies), then verify that direct connections from outside to MySQL and Redis are blocked, while CTFd → MySQL and CTFd → Redis connections succeed.

**Acceptance Scenarios**:

1. **Given** the CTFd namespace policies are applied, **When** an external request arrives for the database port, **Then** it is blocked and the database remains unreachable from outside the namespace.
2. **Given** the CTFd namespace policies are applied, **When** the CTFd application connects to the database, **Then** the connection succeeds normally.
3. **Given** the controller service tries to patch a deployment in the `challenges` namespace, **When** the action is performed, **Then** it succeeds because egress to `challenges` is explicitly permitted for the controller.
4. **Given** the controller service tries to list pods in the `ctfd` namespace itself, **When** the action is attempted, **Then** it is denied by RBAC.

---

### User Story 3 - Workload Permission Scoping (Priority: P3)

The challenge controller and the lifetime daemon each have precisely scoped access rights. The controller can create and manage resources in the `challenges` namespace only. The daemon can read and scale down deployments in `challenges` only. Neither has any cluster-wide permissions.

**Why this priority**: Least-privilege RBAC ensures that even if the controller or daemon process is exploited, the attacker cannot pivot to the broader cluster or modify the `ctfd` namespace.

**Independent Test**: Using impersonation checks, verify that the `challenge-controller` service account is denied list access to pods in the `ctfd` namespace, and that the `challenge-daemon` service account is denied delete access to deployments in the `challenges` namespace.

**Acceptance Scenarios**:

1. **Given** the RBAC resources are applied, **When** the controller service account attempts to list pods in its own (`ctfd`) namespace, **Then** the request is denied.
2. **Given** the RBAC resources are applied, **When** the daemon service account attempts to delete a deployment in `challenges`, **Then** the request is denied (it may only patch replicas to zero).
3. **Given** the RBAC resources are applied, **When** the controller service account patches a deployment in `challenges`, **Then** the action succeeds.

---

### User Story 4 - Pod Security Enforcement (Priority: P3)

Challenge pods cannot be created with elevated privileges. Any pod spec that requests root capabilities, host path access, or privilege escalation is rejected outright. The CTFd namespace accepts baseline-compliant pods, while the challenges namespace requires the stricter restricted profile.

**Why this priority**: Prevents a misconfigured or malicious challenge image from escaping the container boundary through OS-level privilege escalation.

**Independent Test**: Attempt to apply a pod manifest with `privileged: true` to the `challenges` namespace and verify it is rejected by the admission controller.

**Acceptance Scenarios**:

1. **Given** the pod security labels are applied to the `challenges` namespace, **When** an operator attempts to deploy a pod with `privileged: true`, **Then** the admission controller rejects the manifest with a clear error.
2. **Given** a correctly configured restricted-profile challenge pod, **When** it is deployed, **Then** it runs successfully without requiring any privilege escalation.
3. **Given** a challenge pod exceeds its memory limit, **When** the OOM killer acts, **Then** only that pod is terminated and other pods in the namespace are unaffected.

---

### Edge Cases

- What happens if a challenge pod's image needs to bind to a port below 1024? (Restricted pod security does not allow this — challenge images must use ports ≥ 1024.)
- What if the ingress controller namespace label changes? The `challenges` allow-ingress policy is tied to a namespace selector — a rename would silently break ingress to challenges.
- What if DNS is needed over TCP (large responses)? Both UDP/53 and TCP/53 must be permitted to avoid intermittent DNS failures.
- What if a legitimate controller action requires a permission not covered in its Role? The controller will receive an RBAC denial — the Role must be updated deliberately, not by granting broader permissions.
- What if a test pod fails to clean up after a test run? The test script must include cleanup even on failure to avoid leaving privileged test pods in the cluster.

## Requirements *(mandatory)*

### Functional Requirements

**Challenges Namespace — Network Policies**

- **FR-001**: The system MUST enforce a default-deny policy blocking ALL ingress and egress for pods in the `challenges` namespace unless explicitly permitted.
- **FR-002**: The system MUST allow ingress to challenge pods exclusively from the ingress controller namespace on the challenge's designated port (8080 for web, 1337 for pwn, 4444 for misc).
- **FR-003**: The system MUST allow egress from challenge pods to the cluster DNS service on UDP and TCP port 53 only.
- **FR-004**: The system MUST block all egress from challenge pods to the `ctfd` namespace.
- **FR-005**: The system MUST block all egress from challenge pods to the Kubernetes API server. The block targets the in-cluster Kubernetes service ClusterIP (`10.96.0.1/32`) on port 443 — the address that `kubernetes.default.svc.cluster.local` resolves to inside the cluster.
- **FR-006**: The system MUST block all egress from challenge pods to the cloud provider metadata service (169.254.169.254).
- **FR-007**: The system MUST block all pod-to-pod traffic within the `challenges` namespace — this includes same-team pods. The default-deny baseline achieves this automatically; no same-team allow rule is introduced.

**CTFd Namespace — Network Policies**

- **FR-008**: The system MUST enforce a default-deny policy blocking ALL ingress and egress for pods in the `ctfd` namespace unless explicitly permitted.
- **FR-009**: The system MUST allow ingress to CTFd and the controller API only from the ingress controller namespace on port 80.
- **FR-010**: The system MUST allow internal egress within the `ctfd` namespace from CTFd to MySQL on port 3306 and to Redis on port 6379.
- **FR-011**: The system MUST allow egress from the controller pods in `ctfd` to the `challenges` namespace (for pod management operations).
- **FR-012**: The system MUST allow egress to external HTTPS (port 443) exclusively from pods in the `ctfd` namespace that carry the `challenge-controller` label — cert-manager ACME and image pulls are handled outside pod-level egress and do not require this allowance.
- **FR-013**: The system MUST allow egress from `ctfd` namespace pods to the cluster DNS service on UDP and TCP port 53.

**Pod Security Standards**

- **FR-014**: The `challenges` namespace MUST enforce the `restricted` Pod Security Standard directly (no warn/audit transition) — pods requesting privilege escalation, host path volumes, or privileged containers MUST be rejected at admission time. Prior compliance fixes in `bulk_spawn.py` mean existing challenge images are expected to be compliant.
- **FR-015**: The `ctfd` namespace MUST enforce the `baseline` Pod Security Standard.

**RBAC — Controller Service Account**

- **FR-016**: The `challenge-controller` service account MUST have a Role in the `challenges` namespace granting create, get, list, update, patch, and delete on: Deployments, Services, Secrets, Ingresses, and ConfigMaps.
- **FR-017**: The `challenge-controller` service account MUST have no permissions in the `ctfd` namespace.
- **FR-018**: The `challenge-controller` service account MUST NOT have any ClusterRole bindings.

**RBAC — Daemon Service Account**

- **FR-019**: The `challenge-daemon` service account MUST have a Role in the `challenges` namespace granting get, list, and watch on Deployments and Pods, and update and patch on Deployments (for scaling replicas to zero).
- **FR-020**: The `challenge-daemon` service account MUST NOT have delete permission on any resource.
- **FR-021**: The `challenge-daemon` service account MUST have no permissions in the `ctfd` namespace and no ClusterRole bindings.

**Verification Test Suite**

- **FR-022**: The system MUST include four test pod manifests (deny-ctfd, deny-cross-team, deny-kube-api, deny-metadata) that each attempt a blocked connection and expect a timeout or refusal.
- **FR-023**: The system MUST include a test runner script that applies each test pod, waits for completion, evaluates the result, prints PASS or FAIL per test, and cleans up all test pods after the run. Each connection attempt within a test pod MUST use a 5-second timeout; a connection that does not complete within 5 seconds is treated as blocked (PASS).

### Key Entities

- **NetworkPolicy**: A namespace-scoped rule set that controls which pods can send or receive traffic and on which ports; policies are additive (allow-listed) within a default-deny baseline.
- **PodSecurityStandard (PSS)**: A cluster-wide admission policy enforced via namespace labels that restricts what a pod spec may declare (privilege level, volume types, capability requests).
- **Role / RoleBinding**: A namespace-scoped permission grant that defines what API verbs a service account may perform on which resource types within a single namespace.
- **ServiceAccount**: An in-cluster identity assigned to a workload; used by the Kubernetes API to evaluate RBAC permissions for that workload's requests.
- **Test Pod**: A short-lived pod deployed exclusively during verification; it runs a single connection attempt and exits with a success or failure code that the test runner interprets.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 4 network isolation tests (deny-ctfd, deny-cross-team, deny-kube-api, deny-metadata) report PASS — meaning every blocked connection attempt fails to establish a session.
- **SC-002**: A permission check confirms that the controller service account is denied access to pods in its own (`ctfd`) namespace.
- **SC-003**: A permission check confirms that the daemon service account cannot delete deployments in the `challenges` namespace (patch/update only).
- **SC-004**: An attempt to create a privileged pod (`privileged: true`) in the `challenges` namespace is rejected at admission time with an error message referencing the restricted Pod Security Standard.
- **SC-005**: A challenge pod that exceeds its memory limit is terminated in isolation — no other pods in any namespace are affected.
- **SC-006**: Normal CTFd-to-database and CTFd-to-cache communication continues to succeed with all policies applied — no availability regression for the platform.
- **SC-007**: The controller can successfully patch a deployment replica count in the `challenges` namespace with all RBAC policies applied — core challenge lifecycle operations remain functional.

## Clarifications

### Session 2026-03-26

- Q: Which pods in the `ctfd` namespace need external HTTPS (port 443) egress? → A: Only pods carrying the `challenge-controller` label — cert-manager and image pulls operate outside pod-level egress.
- Q: Which address should be blocked to prevent challenge pods from reaching the Kubernetes API? → A: The in-cluster ClusterIP `10.96.0.1/32` on port 443 — the address pods resolve via `kubernetes.default.svc.cluster.local`.
- Q: How long should test pods wait before treating a non-response as a blocked connection (PASS)? → A: 5 seconds — full suite completes in ~30s with no false positives on normal cluster latency.
- Q: Should the `challenges` namespace use warn/audit PSS modes before enforcing restricted? → A: No — apply `enforce=restricted` directly; existing images are already compliant from prior bulk_spawn fixes.
- Q: Should same-team pods be isolated from each other, or only cross-team? → A: All pods isolated from each other including same-team — default-deny achieves this with no extra rules needed.

## Assumptions

- The cluster already has the ingress-nginx controller deployed in a namespace labeled `kubernetes.io/metadata.name: ingress-nginx` (Phase 1 deliverable). The allow-ingress policy for challenges uses this label as a selector.
- The `challenges` namespace already exists and challenge pods carry the labels `team=<id>`, `challenge=<id>`, and `managed-by=ctf-controller` (Phase 3 deliverable).
- Both service accounts (`challenge-controller`, `challenge-daemon`) are already declared in the `ctfd` namespace (Phase 3 deliverable); this phase adds the RBAC bindings only.
- Monitoring and alerting are out of scope for this phase (deferred to v2).
- DNS, image scanning, and ingress TLS configuration are not modified in this phase.
- The Kubernetes cluster's CNI plugin supports NetworkPolicy enforcement (DOKS uses Cilium, which does).

## Out of Scope

- Monitoring, Prometheus, Grafana, Alertmanager, or any metrics stack.
- DNS or TLS configuration changes.
- Container image vulnerability scanning.
- Inter-namespace communication for anything other than the controller/daemon → challenges path and ingress → all services.
