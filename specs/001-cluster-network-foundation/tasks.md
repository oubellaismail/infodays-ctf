# Tasks: Cluster & Networking Foundation

**Input**: Design documents from `specs/001-cluster-network-foundation/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Key reference values** (used throughout — do not change):
- Cluster name: `infodays-ctf` | Region: `fra1` | Node size: `s-4vcpu-8gb` | Node count: `4`
- DOCR name: `infodays-registry` | DOCR tier: `starter`
- Spaces bucket: `infodays-tfstate` | State key: `cluster/terraform.tfstate`
- Namespaces: `ctfd`, `challenges`, `monitoring`
- Ingress chart: `ingress-nginx/ingress-nginx` | Namespace: `ingress-nginx`
- cert-manager chart: `cert-manager/cert-manager` | Namespace: `cert-manager`
- ClusterIssuer name: `letsencrypt-prod`
- Certificates: `ctfd-tls` (namespace: `ctfd`) and `challenges-wildcard-tls` (namespace: `ingress-nginx`)
- K8s min version: `1.28`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Create directory skeleton and bootstrap resources. No Terraform code yet.

- [x] T001 Create directory tree: `infra/spaces-bootstrap/`, `infra/terraform/`, `infra/tests/` (three `mkdir -p` calls from repo root)
- [x] T002 [P] Create `infra/terraform/terraform.tfvars.example` with placeholder lines for all 5 required variables: `do_token`, `do_spaces_access_key`, `do_spaces_secret_key`, `do_dns_token`, `letsencrypt_email` — use `"YOUR_VALUE_HERE"` as the placeholder for each
- [x] T003 [P] Create/update `.gitignore` at repo root — add entries: `infra/terraform/terraform.tfvars`, `infra/terraform/.terraform/`, `infra/terraform/*.tfstate`, `infra/terraform/*.tfstate.backup`, `infra/spaces-bootstrap/.terraform/`, `infra/spaces-bootstrap/*.tfstate`, `infra/spaces-bootstrap/*.tfstate.backup`, `**/.terraform.lock.hcl` (but commit `infra/terraform/.terraform.lock.hcl` — so only ignore inside spaces-bootstrap)
- [x] T004 Create `infra/spaces-bootstrap/main.tf` — declare `terraform {}` block with required provider `digitalocean/digitalocean ~> 2.0`, a `variable "do_token"` (sensitive), a `variable "do_spaces_access_key"` (sensitive), a `variable "do_spaces_secret_key"` (sensitive), a `provider "digitalocean" { token = var.do_token }`, and a `digitalocean_spaces_bucket` resource named `"tfstate"` with `name = "infodays-tfstate"`, `region = "fra1"`, `acl = "private"` and a `versioning { enabled = true }` block

**Checkpoint**: Directory structure exists; `.gitignore` prevents secret files from being committed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core Terraform provider configuration, cluster, and registry — MUST complete before any user story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T005 Create `infra/terraform/providers.tf` with four blocks:
  (1) `terraform {}` block: `required_version = ">= 1.5"`, required providers `digitalocean/digitalocean ~> 2.0`, `hashicorp/kubernetes ~> 2.0`, `hashicorp/helm ~> 2.0`; `backend "s3"` block with `endpoint = "https://fra1.digitaloceanspaces.com"`, `bucket = "infodays-tfstate"`, `key = "cluster/terraform.tfstate"`, `region = "us-east-1"`, `skip_credentials_validation = true`, `skip_metadata_api_check = true`, `skip_region_validation = true`, `force_path_style = true`.
  (2) `provider "digitalocean" { token = var.do_token }`.
  (3) `provider "kubernetes"` block: `host = digitalocean_kubernetes_cluster.infodays.endpoint`, `token = digitalocean_kubernetes_cluster.infodays.kube_config[0].token`, `cluster_ca_certificate = base64decode(digitalocean_kubernetes_cluster.infodays.kube_config[0].cluster_ca_certificate)`.
  (4) `provider "helm"` block with a nested `kubernetes {}` sub-block using the same three attributes as the kubernetes provider above.

- [x] T006 [P] Create `infra/terraform/variables.tf` — declare one `variable` block per variable with `description` and `type` (and `sensitive = true` where applicable). Variables: `do_token` (string, sensitive), `do_spaces_access_key` (string, sensitive), `do_spaces_secret_key` (string, sensitive), `do_dns_token` (string, sensitive), `letsencrypt_email` (string), `cluster_name` (string, default `"infodays-ctf"`), `cluster_region` (string, default `"fra1"`), `cluster_version` (string, default `"1.28"`), `node_size` (string, default `"s-4vcpu-8gb"`), `node_count` (number, default `4`), `registry_name` (string, default `"infodays-registry"`), `registry_tier` (string, default `"starter"`), `use_letsencrypt_staging` (bool, default `false`)

- [x] T007 [P] Create `infra/terraform/cluster.tf` with two resources:
  (1) `digitalocean_kubernetes_cluster` named `"infodays"`: `name = var.cluster_name`, `region = var.cluster_region`, `version = var.cluster_version`, `auto_upgrade = false`, `surge_upgrade = false`, `ha = false`. Nested `node_pool` block: `name = "infodays-workers"`, `size = var.node_size`, `node_count = var.node_count`, `labels = { role = "worker" }`.
  (2) Data source `digitalocean_kubernetes_versions` named `"available"`: `version_prefix = "${var.cluster_version}."` — used to resolve the latest patch version (reference this in the cluster resource as `version = data.digitalocean_kubernetes_versions.available.latest_version`).

- [x] T008 [P] Create `infra/terraform/registry.tf` with the DOCR resource only (pull-secret resources go in Phase 3):
  `digitalocean_container_registry` named `"infodays"`: `name = var.registry_name`, `subscription_tier_slug = var.registry_tier`, `region = var.cluster_region`.

- [x] T009 Create `infra/terraform/outputs.tf` — declare output blocks: `cluster_id` (value: `digitalocean_kubernetes_cluster.infodays.id`), `cluster_endpoint` (value: `digitalocean_kubernetes_cluster.infodays.endpoint`), `cluster_name` (value: `digitalocean_kubernetes_cluster.infodays.name`), `kubeconfig` (value: `base64encode(digitalocean_kubernetes_cluster.infodays.kube_config[0].raw_config)`, sensitive: true), `registry_endpoint` (value: `digitalocean_container_registry.infodays.server_url`), `registry_name` (value: `digitalocean_container_registry.infodays.name`), `ctfd_namespace` (value: `"ctfd"`), `challenges_namespace` (value: `"challenges"`)

**Checkpoint**: `terraform init` succeeds; `terraform plan` shows cluster + registry to be created. No namespaces, network policies, or ingress yet.

---

## Phase 3: User Story 1 — Operator Provisions Cluster from Scratch (Priority: P1) 🎯 MVP

**Goal**: Single `terraform apply` brings cluster to fully operational: namespaces exist, images pullable from DOCR, HTTPS works for `ctfd.infodays.net`, DNS A-records point to ingress LB.

**Independent Test**: Run `bash infra/tests/validate-cluster.sh` and `bash infra/tests/validate-tls.sh` — both MUST exit 0.

### Implementation for User Story 1

- [x] T010 [P] [US1] Create `infra/terraform/namespaces.tf` — three `kubernetes_namespace` resources named `"ctfd"`, `"challenges"`, `"monitoring"` each with `metadata { name = "<namespace>" }`. No PSA labels yet (added in US3). Add `depends_on = [digitalocean_kubernetes_cluster.infodays]` to each.

- [x] T011 [P] [US1] Append to `infra/terraform/registry.tf` — add the docker credentials and pull-secret resources:
  (1) `digitalocean_container_registry_docker_credentials` named `"pull"`: `registry_name = digitalocean_container_registry.infodays.name`, `write = false`, `expiry_seconds = 0` (non-expiring).
  (2) `kubernetes_secret` named `"docr_pull_secret"` using `for_each = toset(["ctfd", "challenges"])`: `metadata { name = "docr-pull-secret", namespace = each.key }`, `type = "kubernetes.io/dockerconfigjson"`, `data = { ".dockerconfigjson" = digitalocean_container_registry_docker_credentials.pull.docker_credentials }`. Add `depends_on = [kubernetes_namespace.ctfd, kubernetes_namespace.challenges]`.
  (3) `kubernetes_default_service_account` named `"patch_docr"` using `for_each = toset(["ctfd", "challenges"])`: `metadata { namespace = each.key }`, `image_pull_secret { name = "docr-pull-secret" }`. Add `depends_on = [kubernetes_secret.docr_pull_secret]`.

- [x] T012 [US1] Create `infra/terraform/ingress.tf` with two resources:
  (1) `kubernetes_namespace` named `"ingress_nginx"`: `metadata { name = "ingress-nginx" }`. `depends_on = [digitalocean_kubernetes_cluster.infodays]`.
  (2) `helm_release` named `"ingress_nginx"`: `name = "ingress-nginx"`, `repository = "https://kubernetes.github.io/ingress-nginx"`, `chart = "ingress-nginx"`, `namespace = "ingress-nginx"`, `create_namespace = false`, `wait = true`, `timeout = 600`. Set values: `controller.service.type = "LoadBalancer"`, `controller.replicaCount = "1"`. Add `depends_on = [kubernetes_namespace.ingress_nginx]`.
  (3) Data source `kubernetes_service` named `"ingress_nginx_lb"`: `metadata { name = "ingress-nginx-controller", namespace = "ingress-nginx" }`. Add `depends_on = [helm_release.ingress_nginx]`. Add `wait_for_load_balancer = true` if supported, otherwise rely on helm `wait = true`.
  (4) Add output `ingress_lb_ip`: `value = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip`.

- [x] T013 [US1] Create `infra/terraform/dns.tf` with two `digitalocean_record` resources:
  (1) Named `"ctfd_a"`: `domain = "infodays.net"`, `type = "A"`, `name = "ctfd"`, `value = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip`, `ttl = 300`. `depends_on = [data.kubernetes_service.ingress_nginx_lb]`.
  (2) Named `"challenges_wildcard_a"`: same attributes but `name = "*.challenges"`. Same `depends_on`.

- [x] T014 [US1] Create `infra/terraform/cert-manager.tf` with these resources in order:
  (1) `kubernetes_namespace` named `"cert_manager"`: `metadata { name = "cert-manager" }`. `depends_on = [digitalocean_kubernetes_cluster.infodays]`.
  (2) `helm_release` named `"cert_manager"`: `name = "cert-manager"`, `repository = "https://charts.jetstack.io"`, `chart = "cert-manager"`, `namespace = "cert-manager"`, `create_namespace = false`, `wait = true`, `timeout = 300`. Set values: `installCRDs = "true"`. `depends_on = [kubernetes_namespace.cert_manager]`.
  (3) `kubernetes_secret` named `"do_dns_token"`: `metadata { name = "do-dns-token", namespace = "cert-manager" }`, `type = "Opaque"`, `data = { "access-token" = var.do_dns_token }`. `depends_on = [helm_release.cert_manager]`.
  (4) `kubectl_manifest` (or `kubernetes_manifest`) named `"cluster_issuer"` — YAML body for a `ClusterIssuer` named `letsencrypt-prod`: `spec.acme.server` = staging URL if `var.use_letsencrypt_staging` else `https://acme-v02.api.letsencrypt.org/directory`; `spec.acme.email = var.letsencrypt_email`; `spec.acme.privateKeySecretRef.name = "letsencrypt-prod-account-key"`; solver: `dns01.digitalocean.tokenSecretRef = { name = "do-dns-token", key = "access-token" }`. `depends_on = [kubernetes_secret.do_dns_token]`.
  Note: Use `kubernetes_manifest` resource from the `hashicorp/kubernetes` provider for CRD objects (ClusterIssuer, Certificate). Add provider `hashicorp/kubernetes` to the `required_providers` in `providers.tf` if not already present.
  (5) `kubernetes_manifest` named `"cert_ctfd"` — YAML body for a `Certificate` named `ctfd-tls` in namespace `ctfd`: `spec.dnsNames = ["ctfd.infodays.net"]`, `spec.issuerRef = { name = "letsencrypt-prod", kind = "ClusterIssuer" }`, `spec.secretName = "ctfd-tls-secret"`. `depends_on = [kubernetes_manifest.cluster_issuer, kubernetes_namespace.ctfd]`.
  (6) `kubernetes_manifest` named `"cert_challenges"` — `Certificate` named `challenges-wildcard-tls` in namespace `ingress-nginx`: `spec.dnsNames = ["*.challenges.infodays.net"]`, same issuerRef, `spec.secretName = "challenges-tls-secret"`. `depends_on = [kubernetes_manifest.cluster_issuer, kubernetes_namespace.ingress_nginx]`.

- [x] T015 [US1] Create `infra/tests/validate-cluster.sh` — bash script that:
  (1) Exports `KUBECONFIG` from Terraform output: `export KUBECONFIG=$(mktemp); terraform -chdir=infra/terraform output -raw kubeconfig | base64 -d > "$KUBECONFIG"`.
  (2) Checks `kubectl get namespace ctfd challenges monitoring` exits 0 — prints PASS/FAIL.
  (3) Checks `kubectl get pods -n ingress-nginx` shows at least one Running pod — prints PASS/FAIL.
  (4) Checks `kubectl get secret docr-pull-secret -n ctfd` exits 0 — prints PASS/FAIL.
  (5) Checks `kubectl get secret docr-pull-secret -n challenges` exits 0 — prints PASS/FAIL.
  (6) Exits 1 if any check failed; exits 0 if all passed.

- [x] T016 [US1] Create `infra/tests/validate-tls.sh` — bash script that:
  (1) Checks cert is issued: `kubectl get certificate ctfd-tls -n ctfd -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` equals `"True"` — prints PASS/FAIL.
  (2) Checks wildcard cert: same command for `challenges-wildcard-tls` in `ingress-nginx` — prints PASS/FAIL.
  (3) Checks TLS connection: `openssl s_client -connect ctfd.infodays.net:443 -servername ctfd.infodays.net </dev/null 2>/dev/null | openssl x509 -noout -checkend 0` exits 0 — prints PASS/FAIL.
  (4) Exits 1 if any check failed; exits 0 if all passed.

**Checkpoint**: `terraform apply` succeeds. `validate-cluster.sh` and `validate-tls.sh` both exit 0. `https://ctfd.infodays.net` shows a valid certificate.

---

## Phase 4: User Story 2 — Challenge Pods Are Network-Isolated (Priority: P2)

**Goal**: Default-deny NetworkPolicy on all namespaces; explicit allowlists for `ctfd` internal traffic; challenge pods cannot reach ctfd namespace, peer pods, K8s API, metadata endpoint, or internet.

**Independent Test**: Run `bash infra/tests/validate-network-isolation.sh` — MUST exit 0.

### Implementation for User Story 2

- [x] T017 [US2] Create `infra/terraform/network-policies.tf` with the following `kubernetes_network_policy` resources. All use `spec.pod_selector {}` (empty = select all pods). All have `policy_types = ["Ingress", "Egress"]` (unless noted). No `ingress` or `egress` rules listed = deny all by default.

  **Default-deny policies** (one per namespace, no allow rules):
  (1) Named `"default_deny_ctfd"`: namespace `ctfd`, `policy_types = ["Ingress", "Egress"]`. No ingress/egress blocks.
  (2) Named `"default_deny_challenges"`: namespace `challenges`, same.
  (3) Named `"default_deny_monitoring"`: namespace `monitoring`, same.

  **Allowlist policies for `ctfd` namespace** (4 separate resources):
  (4) Named `"allow_ctfd_mysql"`: namespace `ctfd`. Ingress only. `ingress[0].from[0].pod_selector.match_labels = { app = "ctfd" }`. `ingress[0].ports[0] = { port = "3306", protocol = "TCP" }`.
  (5) Named `"allow_ctfd_redis"`: namespace `ctfd`. Ingress only. Same structure but port `6379`.
  (6) Named `"allow_ctfd_egress_internet"`: namespace `ctfd`. Egress only. `egress[0].to[0].ip_block.cidr = "0.0.0.0/0"`. `egress[0].ports[0] = { port = "443", protocol = "TCP" }`.
  (7) Named `"allow_ingress_to_ctfd"`: namespace `ctfd`. Ingress only. `ingress[0].from[0].namespace_selector.match_labels = { "kubernetes.io/metadata.name" = "ingress-nginx" }`. `ingress[0].ports[0] = { port = "8000", protocol = "TCP" }`.

  Add `depends_on = [kubernetes_namespace.ctfd, kubernetes_namespace.challenges, kubernetes_namespace.monitoring]` to all resources.

- [x] T018 [US2] Create `infra/tests/validate-network-isolation.sh` — bash script that uses a test pod (`busybox:1.35` image, `uid=1000`, namespace `challenges`, team label `team=999`) to verify isolation:
  (1) Deploy test pod: `kubectl run nettest --image=busybox:1.35 --restart=Never -n challenges --overrides='{"spec":{"securityContext":{"runAsUser":1000}}}' -- sleep 60`.
  (2) Wait for pod Ready: `kubectl wait pod/nettest -n challenges --for=condition=Ready --timeout=30s`.
  (3) Test ctfd namespace unreachable: `kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://ctfd.ctfd.svc.cluster.local 2>&1` — MUST fail/timeout. Print PASS if exit code non-zero.
  (4) Test metadata endpoint blocked: `kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://169.254.169.254 2>&1` — MUST fail. Print PASS if exit code non-zero.
  (5) Test internet blocked: `kubectl exec -n challenges nettest -- wget -qO- --timeout=3 http://example.com 2>&1` — MUST fail. Print PASS if exit code non-zero.
  (6) Cleanup: `kubectl delete pod nettest -n challenges --ignore-not-found`.
  (7) Exit 1 if any check failed; exit 0 if all passed.

**Checkpoint**: `validate-network-isolation.sh` exits 0. Challenge pods cannot reach prohibited destinations.

---

## Phase 5: User Story 3 — Pod Security Standards Enforced at Admission (Priority: P3)

**Goal**: `challenges` namespace enforces `restricted` PSA; `ctfd` enforces `baseline`. Non-compliant pods are rejected at admission.

**Independent Test**: Attempt to deploy a root pod to `challenges` — it MUST be rejected. Deploy a `uid=1000` pod — it MUST be accepted.

### Implementation for User Story 3

- [x] T019 [US3] Update `infra/terraform/namespaces.tf` — add PodSecurity admission labels to the `ctfd` and `challenges` `kubernetes_namespace` resources. For `challenges`: add four labels in `metadata.labels`: `pod-security.kubernetes.io/enforce = "restricted"`, `pod-security.kubernetes.io/enforce-version = "latest"`, `pod-security.kubernetes.io/warn = "restricted"`, `pod-security.kubernetes.io/warn-version = "latest"`. For `ctfd`: same four labels but value `"baseline"`. Do NOT add any PSA labels to the `monitoring` namespace.

- [x] T020 [US3] Create `infra/tests/validate-psa.sh` — bash script that:
  (1) Attempts to deploy a non-compliant pod (runs as root): `kubectl run root-test --image=busybox:1.35 --restart=Never -n challenges --overrides='{"spec":{"securityContext":{"runAsUser":0}}}' -- sleep 5 2>&1`. Captures output. Checks that the command FAILED or output contains "forbidden" / "violates" / "Error". Prints PASS if rejected, FAIL if accepted.
  (2) Attempts to deploy a compliant pod (uid=1000, non-root): `kubectl run uid-test --image=busybox:1.35 --restart=Never -n challenges --overrides='{"spec":{"securityContext":{"runAsUser":1000,"runAsNonRoot":true},"containers":[{"name":"uid-test","image":"busybox:1.35","securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}' -- sleep 5`. Checks exit 0. Prints PASS if accepted.
  (3) Cleanup: `kubectl delete pod uid-test -n challenges --ignore-not-found`.
  (4) Exit 1 if any check failed; exit 0 if all passed.

**Checkpoint**: `validate-psa.sh` exits 0. Root pods are rejected; compliant pods are accepted.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, final validation, and end-of-event teardown tooling.

- [x] T021 [P] Create `infra/spaces-bootstrap/README.md` — document the one-time bootstrap step: prerequisites (DO API token, Spaces access/secret keys), the three commands (`terraform init`, `terraform apply`, confirm bucket created), and a warning that this must be run before `infra/terraform/`.
- [x] T022 [P] Create `infra/terraform/README.md` — document: prerequisites checklist (DNS delegated, API tokens, bootstrap done), `terraform init` → `terraform plan` → `terraform apply` steps, the five validation commands from `quickstart.md`, and the teardown command (`terraform destroy`). Reference `quickstart.md` in `specs/` for full operator runbook.
- [x] T023 Run full validation suite in sequence to confirm all stories pass: `bash infra/tests/validate-cluster.sh && bash infra/tests/validate-tls.sh && bash infra/tests/validate-network-isolation.sh && bash infra/tests/validate-psa.sh`. All MUST exit 0.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. T002, T003, T004 can run in parallel after T001.
- **Foundational (Phase 2)**: Depends on Phase 1 completion. T006, T007, T008 can run in parallel after T005.
- **US1 (Phase 3)**: Depends on Foundational completion. T010, T011 can run in parallel. T012 → T013 → T014 are sequential (ingress IP needed for DNS; DNS needed for cert issuance).
- **US2 (Phase 4)**: Depends on Phase 3 (namespaces must exist). T017 and T018 can run in parallel.
- **US3 (Phase 5)**: Depends on Phase 3 (namespaces must exist). T019 and T020 can run in parallel.
- **Polish (Phase 6)**: Depends on all prior phases. T021 and T022 can run in parallel.

### User Story Dependencies

- **US1**: Requires Foundational phase. No dependency on US2 or US3.
- **US2**: Requires US1 (namespaces must exist before NetworkPolicies reference them).
- **US3**: Requires US1 (namespaces must exist before PSA labels are applied).

### Within Each User Story

- US1: T010/T011 in parallel → T012 → T013 → T014 → T015/T016 in parallel
- US2: T017 and T018 in parallel (independent files)
- US3: T019 and T020 in parallel (independent files)

---

## Parallel Execution Examples

### Foundational Phase (after T005)

```bash
# Run these three tasks simultaneously — different files, no inter-dependencies:
Task T006: Write infra/terraform/variables.tf
Task T007: Write infra/terraform/cluster.tf
Task T008: Write infra/terraform/registry.tf (DOCR resource only)
```

### US1 Phase (after Foundational)

```bash
# Run T010 and T011 simultaneously:
Task T010: Write infra/terraform/namespaces.tf
Task T011: Append pull-secret resources to infra/terraform/registry.tf

# Then sequentially:
Task T012 → Task T013 → Task T014   # (ingress → DNS → cert-manager)

# Then T015 and T016 simultaneously:
Task T015: Write infra/tests/validate-cluster.sh
Task T016: Write infra/tests/validate-tls.sh
```

### US2 and US3 (after US1)

```bash
# Both user stories can start simultaneously once US1 is complete:
# Story 2 track:                 # Story 3 track:
Task T017 (network-policies.tf)  Task T019 (namespaces.tf PSA labels)
Task T018 (validate-isolation)   Task T020 (validate-psa.sh)
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (`terraform apply` — cluster + registry only)
3. Complete Phase 3: US1 (namespaces + ingress + DNS + TLS + DOCR pull secrets)
4. **STOP and VALIDATE**: `validate-cluster.sh` and `validate-tls.sh` both pass
5. Cluster is operational — proceed to US2/US3 for security hardening

### Incremental Delivery

1. Setup + Foundational → cluster and registry exist
2. US1 → Fully operational cluster with HTTPS ✅ (MVP)
3. US2 → Network isolation enforced ✅
4. US3 → Pod admission enforcement ✅
5. Polish → Documentation and final validation ✅

### Parallel Team Strategy

With two implementers after Foundational is done:
- **Implementer A**: US1 (T010–T016 sequentially)
- **Implementer B**: Pre-write T017–T020 without applying; apply after US1 namespaces exist

---

## Notes

- All Terraform resources that depend on the DOKS cluster being ready MUST include `depends_on = [digitalocean_kubernetes_cluster.infodays]` or use a resource that already has an implicit dependency (e.g., using `kubernetes_namespace` outputs in other resources).
- The `kubernetes_manifest` resource requires the CRD to exist in the cluster before Terraform can apply it. cert-manager CRDs are installed by the Helm chart (`installCRDs = "true"`). The `depends_on = [helm_release.cert_manager]` on ClusterIssuer and Certificate resources handles this ordering.
- `digitalocean_container_registry_docker_credentials` with `expiry_seconds = 0` issues non-expiring credentials. For production use, set an expiry and rotate; for a single-day event, non-expiring is acceptable.
- The `kubernetes_default_service_account` resource in T011 patches (not replaces) the default service account. Terraform may show a diff on subsequent runs if the SA has been modified by the cluster — this is safe to apply.
- Test scripts in `infra/tests/` require `kubectl` and `terraform` in `PATH` and must be run from the repo root.
