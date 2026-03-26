# Tasks: Network Hardening & Isolation

**Input**: Design documents from `/specs/005-network-hardening-isolation/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**User goal**: "create the tasks file so that a cheaper llm model can implement without problems"

**Implementation approach**: Each task includes explicit file paths, exact values (ports, selectors, verbs), and a reference to the authoritative source document. No guesswork required — every value is specified below or in the linked section of data-model.md / contracts/.

**Format**: `[ID] [P?] [Story?] Description with file path`
- `[P]` = parallelisable (no shared files, no blocking dependency)
- `[US1]–[US4]` = maps to user story in spec.md

---

## Phase 1: Setup (Directory Structure)

**Purpose**: Create the directory skeleton required by all subsequent tasks.

- [x] T001 Create four new directories in the repository root: `k8s/network-policies/`, `k8s/pod-security/`, `k8s/rbac/`, and `tests/network-isolation/`. These directories must exist before any files are written to them. Use `mkdir -p` or equivalent. Do NOT add any files yet.

**Checkpoint**: Four empty directories exist.

---

## Phase 2: Foundational (Context Read — No Files Written)

**Purpose**: Establish implementation context by reading existing files. This phase produces no output — it ensures the implementer understands what is already in place before writing anything.

**⚠️ CRITICAL**: Read these files before starting any user story. They define what already exists and what must NOT be duplicated.

- [x] T002 Read `infra/terraform/network-policies.tf` in full. Note: default-deny policies for all namespaces already exist there; `allow-ingress-to-challenges` (ports 8080/1337/4444 from ingress-nginx) exists; `allow-challenges-egress-dns` exists; `allow_ctfd_egress_internet` allows ALL ctfd pods to reach 0.0.0.0/0:443 — this is the policy that Phase 4 (US2) will fix. Do NOT modify this file during Phase 2.

- [x] T003 Read `k8s/ctfd/networkpolicy.yaml` in full. Note: it already contains `allow-controller-egress-k8s-api`, `allow-ctfd-egress-controller`, `allow-ctfd-to-controller-ingress`, `allow-ctfd-egress-dns`, `allow-ctfd-egress-mysql`, `allow-ctfd-egress-redis`. These policies are already applied to the cluster; the standalone YAML files created in Phase 4 (US2) must be consistent with them but do not replace them. Do NOT modify this file during Phase 2.

- [x] T004 Read `k8s/controller/rbac.yaml` in full. Note: ServiceAccount `ctf-controller` exists in the `ctfd` namespace; a Role and RoleBinding for `ctf-controller` in the `challenges` namespace exist but have limited verbs (missing `update`, `delete`, `watch` on Deployments; missing `get`, `list`, `update`, `patch`, `delete` on Secrets/Services/Ingresses). The daemon deployment currently uses `serviceAccountName: ctf-controller` — this must change in Phase 5 (US3). Do NOT modify this file during Phase 2.

**Checkpoint**: Implementation context established. User story work can begin.

---

## Phase 3: User Story 1 — Challenge Sandbox Isolation (Priority: P1) 🎯 MVP

**Goal**: Produce standalone kubectl-applicable YAML files for all challenges namespace network policies, plus the complete isolation test suite (4 test pod manifests + runner script). The Terraform policies already enforce the isolation; these files are an independently applicable reference and are required for the verification test suite.

**Independent Test**:
```bash
bash scripts/run-isolation-tests.sh
# All 4 tests must output PASS
```

**Context for this phase** (read before writing any file):
- Allowlist for challenges namespace: `specs/005-network-hardening-isolation/contracts/network-policy-allowlist.md` — "challenges namespace — Allowlist" section
- Test pod specifications: `specs/005-network-hardening-isolation/data-model.md` — "Section 4: Verification Test Pod Specifications"
- All challenge pods carry labels: `team=<id>`, `challenge=<id>`, `managed-by=ctf-controller`
- Test resources MUST use `team=999` per constitution naming conventions

### Implementation for User Story 1

- [x] T005 [P] [US1] Create `k8s/network-policies/challenges-default-deny.yaml`. This is a NetworkPolicy that selects ALL pods in the `challenges` namespace (`podSelector: {}`) and sets `policyTypes: [Ingress, Egress]` with NO ingress or egress rules — this produces a default-deny baseline. Use `metadata.name: default-deny-all` and `metadata.namespace: challenges`. This is a standalone YAML equivalent of the Terraform `kubernetes_network_policy.default_deny_challenges` resource.

- [x] T006 [P] [US1] Create `k8s/network-policies/challenges-allow-ingress.yaml`. This NetworkPolicy selects ALL pods in `challenges` (`podSelector: {}`) and allows ingress from pods in the namespace with label `kubernetes.io/metadata.name: ingress-nginx` on ports 8080/TCP, 1337/TCP, and 4444/TCP. Use `metadata.name: allow-ingress-to-challenges`. This is a standalone YAML equivalent of the Terraform `kubernetes_network_policy.allow_ingress_to_challenges` resource.

- [x] T007 [P] [US1] Create `k8s/network-policies/challenges-allow-dns.yaml`. This NetworkPolicy selects ALL pods in `challenges` (`podSelector: {}`) and allows egress to pods in the namespace with label `kubernetes.io/metadata.name: kube-system` on port 53/UDP AND port 53/TCP. Use `metadata.name: allow-challenges-egress-dns`. This is a standalone YAML equivalent of the Terraform `kubernetes_network_policy.allow_challenges_egress_dns` resource. Both UDP and TCP must be listed as separate `ports` entries.

- [x] T008 [P] [US1] Create `tests/network-isolation/test-deny-ctfd.yaml`. This is a Pod manifest (not a Deployment) that: runs in the `challenges` namespace; uses labels `team: "999"`, `challenge: test-deny-ctfd`, `managed-by: ctf-controller`; runs a single container using image `curlimages/curl:8.6.0` with command `["curl", "--max-time", "5", "-s", "http://ctfd.ctfd.svc.cluster.local"]`; sets `restartPolicy: Never`; sets a full `restricted`-compliant securityContext (see data-model.md Section 2 for required fields: `runAsNonRoot: true`, `runAsUser: 1000`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile.type: RuntimeDefault`). The pod exits non-zero when the connection is blocked (which is the PASS condition for isolation). Use `metadata.name: test-deny-ctfd`.

- [x] T009 [P] [US1] Create `tests/network-isolation/test-deny-cross-team.yaml`. Same structure as T008. Labels: `team: "999"`, `challenge: test-deny-cross-team`, `managed-by: ctf-controller`. Command: `["curl", "--max-time", "5", "-s", "http://team-1-web-1-svc.challenges.svc.cluster.local"]`. This tests that a pod labeled `team=999` cannot reach a service for `team=1`. The `team-1-web-1-svc` service is assumed to exist from Phase 3 bulk_spawn. Use `metadata.name: test-deny-cross-team`.

- [x] T010 [P] [US1] Create `tests/network-isolation/test-deny-kube-api.yaml`. Same structure as T008. Labels: `team: "999"`, `challenge: test-deny-kube-api`, `managed-by: ctf-controller`. Command: `["curl", "--max-time", "5", "-sk", "https://kubernetes.default.svc.cluster.local"]`. The `-k` flag skips TLS verification (the pod has no CA bundle). Exit non-zero when blocked. Use `metadata.name: test-deny-kube-api`.

- [x] T011 [P] [US1] Create `tests/network-isolation/test-deny-metadata.yaml`. Same structure as T008. Labels: `team: "999"`, `challenge: test-deny-metadata`, `managed-by: ctf-controller`. Command: `["curl", "--max-time", "5", "-s", "http://169.254.169.254/metadata/v1"]`. Exit non-zero when blocked. Use `metadata.name: test-deny-metadata`.

- [x] T012 [US1] Create `scripts/run-isolation-tests.sh` (depends on T008–T011). This Bash 5 script must:
  1. Define a NAMESPACE variable set to `challenges`
  2. Define an array of the four test pod manifest paths (relative to the repo root)
  3. For each test pod manifest: run `kubectl apply -f <manifest>`, then poll `kubectl get pod <pod-name> -n challenges -o jsonpath='{.status.phase}'` every 2 seconds until the phase is `Succeeded` or `Failed` (max 30s poll timeout before declaring ERROR)
  4. Get the pod's exit code via `kubectl get pod <pod-name> -n challenges -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}'`
  5. If exit code is non-zero (or if connection errored): print `[PASS] <test-name> — connection blocked`
  6. If exit code is 0 (connection succeeded): print `[FAIL] <test-name> — connection NOT blocked`
  7. Always clean up: `kubectl delete pod <pod-name> -n challenges --ignore-not-found` (run even if test fails — use a trap or explicit cleanup after each test)
  8. At the end: print a summary line "N/4 isolation tests passed" and exit with code 0 if all passed, code 1 if any failed

  The script MUST be executable (`chmod +x`) and include `set -euo pipefail` at the top. Use `#!/usr/bin/env bash`.

**Checkpoint**: `bash scripts/run-isolation-tests.sh` runs to completion (all 4 tests must PASS if cluster policies are applied).

---

## Phase 4: User Story 2 — CTFd Namespace Isolation (Priority: P2)

**Goal**: Fix the over-broad external HTTPS egress in Terraform, and produce standalone YAML files for the ctfd namespace policies. The `k8s/ctfd/networkpolicy.yaml` already has most ctfd internal policies applied; this phase fixes the Terraform gap and provides standalone equivalents.

**Independent Test**:
```bash
# After terraform apply, verify pod selector on the updated policy:
kubectl get networkpolicy allow-ctfd-egress-internet -n ctfd -o jsonpath='{.spec.podSelector}'
# Expected: {"matchLabels":{"app":"controller-api"}}
```

**Context for this phase**:
- Allowlist for ctfd namespace: `specs/005-network-hardening-isolation/contracts/network-policy-allowlist.md` — "ctfd namespace — Allowlist" section
- Existing ctfd policies already in `k8s/ctfd/networkpolicy.yaml`: default-deny is in Terraform; internal policies (mysql, redis, controller, dns) are in `k8s/ctfd/networkpolicy.yaml`

### Implementation for User Story 2

- [x] T013 [US2] Update `infra/terraform/network-policies.tf`. Find the resource block named `kubernetes_network_policy` `allow_ctfd_egress_internet` (resource type `kubernetes_network_policy`, resource label `allow_ctfd_egress_internet`). Inside its `spec` block, change the `pod_selector {}` (empty, matches all pods) to:
  ```hcl
  pod_selector {
    match_labels = {
      app = "controller-api"
    }
  }
  ```
  Do NOT change any other field in this resource. Do NOT modify any other resource in the file. After the edit, the resource should allow egress to 0.0.0.0/0:443/TCP from pods with label `app=controller-api` only.

- [x] T014 [P] [US2] Create `k8s/network-policies/ctfd-default-deny.yaml`. NetworkPolicy selecting ALL pods in `ctfd` (`podSelector: {}`) with `policyTypes: [Ingress, Egress]` and no rules. `metadata.name: default-deny-all`, `metadata.namespace: ctfd`. Standalone YAML equivalent of `kubernetes_network_policy.default_deny_ctfd` in Terraform.

- [x] T015 [P] [US2] Create `k8s/network-policies/ctfd-allow-internal.yaml`. This is a multi-document YAML file (separated by `---`) containing six NetworkPolicy resources for the `ctfd` namespace. Use the "ctfd namespace — Allowlist" table in `specs/005-network-hardening-isolation/contracts/network-policy-allowlist.md` as the authoritative source. The six policies are:
  1. `allow-ingress-to-ctfd`: ingress from `ingress-nginx` namespace → all ctfd pods → port 8000/TCP
  2. `allow-ctfd-egress-dns`: egress from all ctfd pods → `kube-system` namespace → port 53/UDP + 53/TCP
  3. `allow-ctfd-egress-mysql`: egress from `app: ctfd` pods → `app: mysql` pods → port 3306/TCP
  4. `allow-ctfd-egress-redis`: egress from `app: ctfd` pods → `app: redis` pods → port 6379/TCP
  5. `allow-ctfd-egress-controller`: egress from `app: ctfd` pods → `app: controller-api` pods → port 5000/TCP
  6. `allow-ctfd-to-controller-ingress`: ingress to `app: controller-api` pods from `app: ctfd` pods → port 5000/TCP

  These are YAML equivalents of the policies already in `k8s/ctfd/networkpolicy.yaml` and the Terraform file. They must be consistent with what exists there but are standalone for kubectl application.

- [x] T016 [P] [US2] Create `k8s/network-policies/ctfd-allow-controller-egress.yaml`. Multi-document YAML with two NetworkPolicy resources for the `ctfd` namespace:
  1. `allow-controller-egress-k8s-api`: egress from pods matching `app: controller-api` OR `app: controller-daemon` to the K8s API server IP on port 443/TCP. Use the same IP that is in `k8s/ctfd/networkpolicy.yaml` for the `allow-controller-egress-k8s-api` policy — read that file and copy the exact CIDR value.
  2. `allow-ctfd-egress-internet` (CORRECTED version): egress from pods matching `app: controller-api` ONLY to `0.0.0.0/0` on port 443/TCP. This is the fixed version — controller pods only, not all ctfd pods.

**Checkpoint**: After `terraform apply -target=kubernetes_network_policy.allow_ctfd_egress_internet`, verify the pod selector is `app: controller-api`.

---

## Phase 5: User Story 3 — Workload Permission Scoping (Priority: P3)

**Goal**: Deliver complete RBAC for both service accounts. Create `k8s/rbac/challenge-controller-rbac.yaml` with the full permission set (including previously missing verbs), create `k8s/rbac/challenge-daemon-rbac.yaml` for the daemon (new service account with read-only + patch permissions), and update the daemon deployment to use its dedicated service account.

**Independent Test**:
```bash
kubectl auth can-i list pods -n ctfd \
  --as=system:serviceaccount:ctfd:ctf-controller
# Expected: no

kubectl auth can-i delete deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: no

kubectl auth can-i patch deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: yes
```

**Context for this phase**:
- Complete permission matrix: `specs/005-network-hardening-isolation/contracts/rbac-permissions.md`
- Existing partial RBAC: `k8s/controller/rbac.yaml` (read this first — the new file supersedes it)
- Daemon deployment that needs SA update: `k8s/controller/daemon-deployment.yaml`

### Implementation for User Story 3

- [x] T017 [US3] Create `k8s/rbac/challenge-controller-rbac.yaml`. This file contains four YAML documents (separated by `---`):

  **Document 1** — ServiceAccount (same as in `k8s/controller/rbac.yaml`, reproduced here for standalone apply):
  ```yaml
  kind: ServiceAccount
  metadata:
    name: ctf-controller
    namespace: ctfd
  ```

  **Document 2** — Role in `challenges` namespace. Name: `ctf-controller`. Rules (use `specs/005-network-hardening-isolation/contracts/rbac-permissions.md` as the authoritative source):
  - `apiGroups: [apps]`, `resources: [deployments]`, `verbs: [get, list, watch, create, update, patch, delete]`
  - `apiGroups: [""]`, `resources: [services]`, `verbs: [get, list, create, update, patch, delete]`
  - `apiGroups: [""]`, `resources: [secrets]`, `verbs: [get, list, create, update, patch, delete]`
  - `apiGroups: [networking.k8s.io]`, `resources: [ingresses]`, `verbs: [get, list, create, update, patch, delete]`

  **Document 3** — RoleBinding in `challenges` namespace. Name: `ctf-controller`. Binds Role `ctf-controller` (in `challenges`) to ServiceAccount `ctf-controller` in namespace `ctfd`.

  **Document 4** — A comment block OR separate Role+RoleBinding for the `ingress-nginx` namespace (same as in `k8s/controller/rbac.yaml`: Role `ctf-controller-nginx` in `ingress-nginx` with `get, patch` on `configmaps`; RoleBinding in `ingress-nginx` binding to SA `ctf-controller` in `ctfd`).

  After creating this file, add a deprecation comment at the top of `k8s/controller/rbac.yaml`: `# DEPRECATED: Superseded by k8s/rbac/challenge-controller-rbac.yaml — do not apply this file after Phase 5`.

- [x] T018 [US3] Create `k8s/rbac/challenge-daemon-rbac.yaml`. This file contains three YAML documents:

  **Document 1** — ServiceAccount: `name: ctf-daemon`, `namespace: ctfd`

  **Document 2** — Role in `challenges` namespace. Name: `ctf-daemon`. Rules (authoritative source: `specs/005-network-hardening-isolation/contracts/rbac-permissions.md`):
  - `apiGroups: [apps]`, `resources: [deployments]`, `verbs: [get, list, watch, update, patch]` — NOTE: NO `delete`, NO `create`
  - `apiGroups: [""]`, `resources: [pods]`, `verbs: [get, list, watch]`

  **Document 3** — RoleBinding in `challenges` namespace. Name: `ctf-daemon`. Binds Role `ctf-daemon` (in `challenges`) to ServiceAccount `ctf-daemon` in namespace `ctfd`.

- [x] T019 [US3] Update `k8s/controller/daemon-deployment.yaml`. Find the field `serviceAccountName: ctf-controller` in the pod spec and change it to `serviceAccountName: ctf-daemon`. This is the only change to make in this file. The `ctf-daemon` SA is created in T018 and must be applied before the daemon deployment is restarted.

**Checkpoint**: Apply `kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml` and `kubectl apply -f k8s/rbac/challenge-daemon-rbac.yaml`, then run the three `kubectl auth can-i` commands above.

---

## Phase 6: User Story 4 — Pod Security Enforcement (Priority: P3)

**Goal**: Provide a standalone kubectl-applicable YAML file for the PSS namespace labels. The labels are already managed by Terraform (`infra/terraform/namespaces.tf`) — this file enables manual application or cluster recovery without Terraform.

**Independent Test**:
```bash
kubectl get namespace challenges -o jsonpath='{.metadata.labels}' | grep restricted
# Expected: output contains pod-security.kubernetes.io/enforce: restricted

kubectl run test-privileged --image=alpine -n challenges \
  --overrides='{"spec":{"containers":[{"name":"t","image":"alpine","securityContext":{"privileged":true}}]}}'
# Expected: Error from server (Forbidden): ...violates PodSecurity "restricted"
```

**Context for this phase**:
- PSS label values: `specs/005-network-hardening-isolation/data-model.md` — "Section 2: PodSecurityStandard Configuration" table
- Existing Terraform source: `infra/terraform/namespaces.tf` (labels already applied)

### Implementation for User Story 4

- [x] T020 [US4] Create `k8s/pod-security/namespace-labels.yaml`. This is a two-document YAML file (separated by `---`) containing two Namespace resources that set PSS labels via `metadata.labels`:

  **Document 1** — challenges namespace:
  - `metadata.name: challenges`
  - Labels: `pod-security.kubernetes.io/enforce: restricted`, `pod-security.kubernetes.io/enforce-version: latest`, `pod-security.kubernetes.io/warn: restricted`, `pod-security.kubernetes.io/warn-version: latest`
  - Do NOT include other namespace fields — this is a strategic merge patch target

  **Document 2** — ctfd namespace:
  - `metadata.name: ctfd`
  - Labels: `pod-security.kubernetes.io/enforce: baseline`, `pod-security.kubernetes.io/enforce-version: latest`, `pod-security.kubernetes.io/warn: baseline`, `pod-security.kubernetes.io/warn-version: latest`

  Both documents use `apiVersion: v1`, `kind: Namespace`. Include a comment at the top: `# Standalone PSS label application — authoritative source is infra/terraform/namespaces.tf`.

**Checkpoint**: `kubectl apply -f k8s/pod-security/namespace-labels.yaml` applies without error. Verify with `kubectl get namespace challenges -o jsonpath='{.metadata.labels}'`.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verification steps and housekeeping across all user stories.

- [x] T021 [P] Walk through `specs/005-network-hardening-isolation/quickstart.md` end to end on the live cluster. Run each `kubectl` command in the "Step 2: Apply RBAC" and "Step 3: Verify PSS labels" sections. Fix any commands in quickstart.md that produce unexpected output. This is a manual validation step — no file creation required unless fixes are needed.

- [x] T022 [P] Verify `infra/terraform/network-policies.tf` change from T013 is consistent with `k8s/network-policies/ctfd-allow-controller-egress.yaml` created in T016. Both documents must describe the same allow rule: egress from `app: controller-api` pods to `0.0.0.0/0:443/TCP`. If they differ, reconcile them so both are identical in intent.

- [x] T023 Check that `k8s/controller/daemon-deployment.yaml` (updated in T019) and `k8s/rbac/challenge-daemon-rbac.yaml` (created in T018) are consistent: the `serviceAccountName` in the deployment must match the `name` in the ServiceAccount document in the RBAC file (both must be `ctf-daemon`).

**Checkpoint**: All deliverables from Plan.md are present, all `kubectl auth can-i` checks pass, and `bash scripts/run-isolation-tests.sh` exits 0.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — must complete before any user story
- **Phase 3 (US1)**: Depends on Phase 2 — can start independently of US2/US3/US4
- **Phase 4 (US2)**: Depends on Phase 2 — can start independently of US1/US3/US4
- **Phase 5 (US3)**: Depends on Phase 2 — can start independently of US1/US2/US4
- **Phase 6 (US4)**: Depends on Phase 2 — can start independently of US1/US2/US3
- **Phase 7 (Polish)**: Depends on all user story phases being complete

### User Story Dependencies

- **US1 (P1)**: No dependency on other user stories. Can be verified independently once T005–T012 are applied.
- **US2 (P2)**: No dependency on US1. The Terraform fix (T013) is independent.
- **US3 (P3)**: T019 (daemon deployment update) should be applied AFTER T018 (daemon SA creation). No dependency on US1 or US2.
- **US4 (P3)**: Fully independent. PSS labels may already be applied via Terraform.

### Within Each User Story

- T005–T011 within US1: All [P] — write all YAML files in parallel
- T012 within US1: Depends on T008–T011 (references the test pod names)
- T013 within US2: Independent Terraform edit
- T014–T016 within US2: All [P] — write all YAML files in parallel
- T017 within US3: Independent of T018
- T018 within US3: Independent of T017
- T019 within US3: Must follow T018 (SA must exist before deployment references it)

---

## Parallel Execution Examples

### User Story 1 (YAML files — all parallel):
```
Parallel Group A (T005, T006, T007):
  Task: Create k8s/network-policies/challenges-default-deny.yaml
  Task: Create k8s/network-policies/challenges-allow-ingress.yaml
  Task: Create k8s/network-policies/challenges-allow-dns.yaml

Parallel Group B (T008, T009, T010, T011):
  Task: Create tests/network-isolation/test-deny-ctfd.yaml
  Task: Create tests/network-isolation/test-deny-cross-team.yaml
  Task: Create tests/network-isolation/test-deny-kube-api.yaml
  Task: Create tests/network-isolation/test-deny-metadata.yaml

Sequential after Group B:
  Task T012: Create scripts/run-isolation-tests.sh
```

### User Story 2 (parallel YAML + sequential Terraform):
```
Parallel Group (T014, T015, T016):
  Task: Create k8s/network-policies/ctfd-default-deny.yaml
  Task: Create k8s/network-policies/ctfd-allow-internal.yaml
  Task: Create k8s/network-policies/ctfd-allow-controller-egress.yaml

Sequential (T013): Edit infra/terraform/network-policies.tf
```

### User Story 3 (parallel RBAC files, sequential deployment update):
```
Parallel (T017, T018):
  Task: Create k8s/rbac/challenge-controller-rbac.yaml
  Task: Create k8s/rbac/challenge-daemon-rbac.yaml

Sequential after T018 (T019): Update k8s/controller/daemon-deployment.yaml
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Create directories
2. Complete Phase 2: Read context files
3. Complete Phase 3: US1 (challenges namespace YAML + test suite)
4. **VALIDATE**: `bash scripts/run-isolation-tests.sh` — all 4 PASS
5. Demonstrate: network isolation is enforced and verifiable

### Incremental Delivery

1. Setup (Phase 1) + Context (Phase 2) → Baseline ready
2. US1 (Phase 3) → Challenge sandbox isolation verifiable ✅
3. US2 (Phase 4) → CTFd namespace isolation complete + Terraform fix applied ✅
4. US3 (Phase 5) → Least-privilege RBAC in place, daemon has dedicated SA ✅
5. US4 (Phase 6) → PSS labels standalone YAML available ✅
6. Polish (Phase 7) → Full end-to-end validation complete

---

## Notes

- Tasks marked `[P]` write to distinct files with no shared dependencies — safe to run simultaneously
- Every YAML file task references a specific section of data-model.md or contracts/ — use those as the authoritative source for exact values (ports, selectors, verbs, labels)
- Never duplicate content from `k8s/ctfd/networkpolicy.yaml` into new files — the standalone YAMLs in `k8s/network-policies/` are for independent reference/recovery, not replacement
- The deprecation comment on `k8s/controller/rbac.yaml` (T017) signals that the old file should not be re-applied — it does NOT delete the file
- Commit after each checkpoint (after each user story phase) to maintain a clean history per story
