# Research: Network Hardening & Isolation

**Branch**: `005-network-hardening-isolation`
**Date**: 2026-03-26
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## Decision 1: Blocking Specific CIDRs in NetworkPolicy

**Decision**: Use default-deny + allowlist pattern. Do NOT use `ipBlock` with `except` to "deny" specific CIDRs.

**Rationale**: Kubernetes NetworkPolicy is strictly additive/allowlist-based — there is no explicit deny construct. The `except` field in `ipBlock` only narrows an allow rule (e.g., allow 0.0.0.0/0 except 10.96.0.1/32). This would require writing a broad allow rule that the `except` then carves out of, which is more complex and more permissive than needed. The cleaner, safer approach is: write a default-deny-all baseline, then add only the specific allow rules needed. Traffic to 10.96.0.1/32 (K8s API ClusterIP) and 169.254.169.254/32 (DO metadata) is blocked by the absence of any allow rule.

**Confirmed evidence**: `infra/terraform/network-policies.tf` already implements this pattern.

**Alternatives considered**:
- `ipBlock.except` on allow-all egress: rejected — requires a broad allow rule that is harder to audit and violates least-privilege principle.
- Port-only blocking via iptables: rejected — out of scope and not portable.

---

## Decision 2: Ingress-nginx Namespace Selector Label

**Decision**: Use `kubernetes.io/metadata.name: ingress-nginx` as the `namespaceSelector` in NetworkPolicy rules that allow ingress from the ingress controller.

**Rationale**: This label is automatically applied by Kubernetes 1.21+ to every namespace as part of its default label set. It is independent of how the namespace was created (Helm, kubectl, Terraform). It does not require any custom labeling step and is the Kubernetes-recommended approach.

**Confirmed evidence**: Already used in `infra/terraform/network-policies.tf` lines 58 and 229.

**Alternatives considered**:
- Custom label on ingress-nginx namespace: rejected — requires an additional labeling step and fails if namespace is recreated.
- PodSelector matching ingress pods: rejected — tightly couples policy to pod labels that may change across Helm chart versions.

---

## Decision 3: PSS `restricted` Profile — Required securityContext Fields

**Decision**: All four fields are required for PSS `restricted` compliance:
1. `containers[].securityContext.allowPrivilegeEscalation: false`
2. `containers[].securityContext.capabilities.drop: ["ALL"]`
3. `pod.spec.securityContext.runAsNonRoot: true`
4. `pod.spec.securityContext.seccompProfile.type: RuntimeDefault`

**Rationale**: The `restricted` profile requires these fields to prevent privilege escalation, capability abuse, and missing seccomp filtering. All four are already set in `controller/bulk_spawn.py` (the code that generates challenge pod specs), confirming that existing challenge pods are compliant.

**Challenge runtime compatibility**:
- Flask on port 8080: ✅ No issues
- socat on port 1337: ✅ No issues (runs as UID 1000 without capabilities)
- Python puzzle on port 4444: ✅ No issues
- Any port < 1024: ❌ Would require CAP_NET_BIND_SERVICE — incompatible with `restricted`. All challenge ports (8080, 1337, 4444) are above 1024.

**Confirmed evidence**: `controller/bulk_spawn.py` lines 155–180 implement all required fields with `run_as_user=1000`.

---

## Decision 4: Cross-Namespace RBAC Pattern (No ClusterRole)

**Decision**: A Role defined in the target namespace (`challenges`) + a RoleBinding in the same namespace (`challenges`) that references a ServiceAccount from a different namespace (`ctfd`) is valid Kubernetes RBAC and does NOT require a ClusterRole.

**Rationale**: RoleBinding subjects may reference ServiceAccounts from any namespace. Only the Role and RoleBinding themselves must be namespace-scoped to the target. This provides least-privilege access: the ServiceAccount can only act in the namespace where the RoleBinding lives.

**Confirmed evidence**: `k8s/controller/rbac.yaml` already implements this pattern for `ctf-controller` (SA in `ctfd`, Role + RoleBinding in `challenges`).

**Alternatives considered**:
- ClusterRole + RoleBinding: rejected — ClusterRoles are visible cluster-wide and expand the blast radius of any SA compromise. Spec explicitly prohibits this.
- ClusterRole + ClusterRoleBinding: rejected — grants cluster-wide access, directly violating the spec and constitution.

---

## Decision 5: PSS Namespace Label Format

**Decision**: Use `pod-security.kubernetes.io/enforce: restricted` with `pod-security.kubernetes.io/enforce-version: latest`.

**Rationale**: `latest` tracks the current Kubernetes version's PSS definition automatically. For DOKS (managed, auto-upgraded), this ensures policies stay current without manual intervention. Specifying a fixed version (e.g., `v1.29`) risks drift as the cluster is upgraded.

**Confirmed evidence**: `infra/terraform/namespaces.tf` already applies these labels with `latest` for both `ctfd` (baseline) and `challenges` (restricted), including matching `warn` labels.

---

## Decision 6: External HTTPS Egress Scoping (Clarification Q1)

**Decision**: The `allow-ctfd-egress-internet` policy (port 443) must be scoped to pods carrying the `app: controller-api` label, not all ctfd namespace pods.

**Rationale**: Cert-manager ACME challenges are handled by cert-manager running in its own namespace — ctfd pods do not need port 443 for TLS certificate issuance. Image pulls are performed by the node kubelet, not pod-level egress. Allowing all ctfd pods to reach external HTTPS gives a compromised CTFd container an exfiltration path.

**Current gap**: `infra/terraform/network-policies.tf` currently has `pod_selector {}` (matches all pods) on the internet egress rule. This needs to be corrected to `pod_selector { match_labels = { app = "controller-api" } }`.

**Alternatives considered**:
- Remove external HTTPS entirely: rejected — the controller may need to reach the DigitalOcean API for operational tasks.
- Allow both controller-api and controller-daemon: worth considering; daemon currently has no external HTTPS need but adding it pre-emptively adds unnecessary surface area.

---

## Decision 7: Kubernetes API Server Blocking (Clarification Q2)

**Decision**: Block egress to the in-cluster Kubernetes service ClusterIP `10.96.0.1/32` on port 443.

**Rationale**: Challenge pods resolve `kubernetes.default.svc.cluster.local` to `10.96.0.1` (the default ClusterIP assigned to the `kubernetes` service). Blocking this ClusterIP is sufficient to prevent pods from reaching the K8s API via the standard in-cluster path. The external API server IP is not required because pod-level access to the API always routes through this ClusterIP.

**Implementation**: The default-deny egress policy already blocks all egress. The absence of an allow rule for `10.96.0.1/32:443` is sufficient. An explicit ipBlock deny rule is not needed or possible in Kubernetes NetworkPolicy.

---

## Decision 8: Test Connection Timeout (Clarification Q3)

**Decision**: 5 seconds per connection attempt.

**Rationale**: Standard timeout for blocked-connection tests. Gives the full test suite a completion time of ~30 seconds (5 s × 4 tests + kubectl overhead). Short enough to be practical in CI; long enough to distinguish a dropped-packet timeout from a fast TCP RST.

**Implementation**: `curl --max-time 5` or `nc -w 5 -z` inside test pods. Exit code non-zero = connection failed = PASS for the isolation test.

---

## Decision 9: PSS Rollout Mode (Clarification Q4)

**Decision**: Apply `enforce=restricted` directly without a warn/audit transition period.

**Rationale**: `controller/bulk_spawn.py` already sets all required `restricted` PSS securityContext fields. The integration-fixes branch (`005-integration-fixes`) explicitly fixed PodSecurity compliance in bulk_spawn. A warn/audit transition would add operational complexity with no benefit.

---

## Decision 10: Intra-Team Pod Isolation (Clarification Q5)

**Decision**: All pods in `challenges` namespace are isolated from each other, including pods belonging to the same team.

**Rationale**: The default-deny baseline already blocks all pod-to-pod traffic regardless of team label. Introducing a same-team allow rule would add complexity and surface area with no gameplay benefit (teams share one CTFd account and don't need inter-pod communication).

---

## Existing Implementation Status

| Component | Already Implemented | Gap |
|-----------|-------------------|-----|
| Default-deny NetworkPolicy (challenges) | ✅ Terraform | Standalone YAML needed |
| Default-deny NetworkPolicy (ctfd) | ✅ Terraform | Standalone YAML needed |
| challenges ingress from ingress-nginx | ✅ Terraform | Standalone YAML needed |
| challenges DNS egress | ✅ Terraform | Standalone YAML needed |
| ctfd DNS egress | ✅ k8s/ctfd/networkpolicy.yaml | Standalone YAML in k8s/network-policies/ |
| ctfd MySQL/Redis egress | ✅ k8s/ctfd/networkpolicy.yaml | Standalone YAML in k8s/network-policies/ |
| ctfd → controller internal | ✅ k8s/ctfd/networkpolicy.yaml | Standalone YAML in k8s/network-policies/ |
| ctfd external HTTPS egress | ✅ Terraform (too broad) | **Fix**: scope to controller-api pods |
| PSS labels (challenges: restricted) | ✅ Terraform | Standalone YAML needed |
| PSS labels (ctfd: baseline) | ✅ Terraform | Standalone YAML needed |
| ctf-controller SA + Role + RoleBinding | ✅ k8s/controller/rbac.yaml (partial) | **Fix**: add missing verbs (update, delete, watch, get/list on all resources) |
| ctf-daemon SA + Role + RoleBinding | ❌ Does not exist | **Create**: k8s/rbac/challenge-daemon-rbac.yaml |
| Isolation test pods (4×) | ❌ Does not exist | **Create**: tests/network-isolation/ |
| run-isolation-tests.sh | ❌ Does not exist | **Create**: scripts/run-isolation-tests.sh |
