# Data Model: Network Hardening & Isolation

**Branch**: `005-network-hardening-isolation`
**Date**: 2026-03-26

This feature is infrastructure configuration. "Entities" are Kubernetes resource types. This document describes each resource group, its key attributes, and the relationships between them.

---

## 1. NetworkPolicy Resources

### 1a. challenges namespace

| Resource Name | Scope | Selector | Direction | Allowed Traffic |
|---------------|-------|----------|-----------|----------------|
| `default-deny-all` | challenges | All pods (`{}`) | Ingress + Egress | None (baseline block) |
| `allow-ingress-to-challenges` | challenges | All pods (`{}`) | Ingress | From `ingress-nginx` namespace → ports 8080 (TCP), 1337 (TCP), 4444 (TCP) |
| `allow-challenges-egress-dns` | challenges | All pods (`{}`) | Egress | To `kube-system` namespace → port 53 (UDP), 53 (TCP) |

**What is NOT allowed** (blocked by absence of allow rules under default-deny):
- Pod-to-pod traffic within challenges namespace
- Egress to ctfd namespace
- Egress to Kubernetes API ClusterIP (10.96.0.1/32:443)
- Egress to DO metadata service (169.254.169.254/32:80)
- Egress to any other external address

### 1b. ctfd namespace

| Resource Name | Scope | Selector | Direction | Allowed Traffic |
|---------------|-------|----------|-----------|----------------|
| `default-deny-all` | ctfd | All pods (`{}`) | Ingress + Egress | None (baseline block) |
| `allow-ingress-to-ctfd` | ctfd | All pods (`{}`) | Ingress | From `ingress-nginx` namespace → port 8000 (TCP) |
| `allow-ctfd-egress-dns` | ctfd | All pods (`{}`) | Egress | To `kube-system` namespace → port 53 UDP+TCP |
| `allow-ctfd-egress-mysql` | ctfd | `app: ctfd` pods | Egress | To `app: mysql` pods → port 3306 (TCP) |
| `allow-ctfd-egress-redis` | ctfd | `app: ctfd` pods | Egress | To `app: redis` pods → port 6379 (TCP) |
| `allow-ctfd-egress-controller` | ctfd | `app: ctfd` pods | Egress | To `app: controller-api` pods → port 5000 (TCP) |
| `allow-ctfd-to-controller-ingress` | ctfd | `app: controller-api` pods | Ingress | From `app: ctfd` pods → port 5000 (TCP) |
| `allow-controller-egress-k8s-api` | ctfd | `app: controller-api` OR `app: controller-daemon` pods | Egress | To cluster K8s API IP → port 443 (TCP) |
| `allow-ctfd-egress-internet` | ctfd | **`app: controller-api` pods only** | Egress | To 0.0.0.0/0 → port 443 (TCP) |

> **Note on `allow-ctfd-egress-internet`**: Currently defined in Terraform with `pod_selector {}` (all pods). Phase 5 updates this to `pod_selector { match_labels = { app = "controller-api" } }`.

---

## 2. PodSecurityStandard Configuration

Applied as namespace labels.

| Namespace | Enforce Level | Enforce Version | Warn Level | Warn Version |
|-----------|--------------|----------------|------------|-------------|
| `challenges` | `restricted` | `latest` | `restricted` | `latest` |
| `ctfd` | `baseline` | `latest` | `baseline` | `latest` |

**What `restricted` blocks** (relevant to challenge pods):
- `privileged: true` containers
- `allowPrivilegeEscalation: true`
- Missing `capabilities.drop: ["ALL"]`
- Missing `runAsNonRoot: true`
- Missing `seccompProfile`
- Host path volumes, host namespaces, host ports

**What challenge pods must set** (already implemented in bulk_spawn.py):
```
containers[].securityContext:
  allowPrivilegeEscalation: false
  capabilities.drop: ["ALL"]
  runAsNonRoot: true
  runAsUser: 1000
pod.spec.securityContext:
  seccompProfile.type: RuntimeDefault
```

---

## 3. RBAC Resources

### 3a. challenge-controller (Service Account)

**Identity**: `system:serviceaccount:ctfd:ctf-controller`

| Resource | Namespace | Role | Verbs |
|----------|-----------|------|-------|
| Deployments | challenges | ctf-controller | get, list, watch, create, update, patch, delete |
| Services | challenges | ctf-controller | get, list, create, update, patch, delete |
| Secrets | challenges | ctf-controller | get, list, create, update, patch, delete |
| Ingresses | challenges | ctf-controller | get, list, create, update, patch, delete |
| ConfigMaps | ingress-nginx | ctf-controller-nginx | get, patch |

**Explicit denials** (no RoleBinding exists for these):
- Any resource in `ctfd` namespace
- Any ClusterRole binding

### 3b. challenge-daemon (Service Account)

**Identity**: `system:serviceaccount:ctfd:ctf-daemon`

| Resource | Namespace | Role | Verbs |
|----------|-----------|------|-------|
| Deployments | challenges | ctf-daemon | get, list, watch, update, patch |
| Pods | challenges | ctf-daemon | get, list, watch |

**Explicit denials**:
- delete on any resource (only patch/update to set replicas=0)
- Any resource in `ctfd` namespace
- Any ClusterRole binding

---

## 4. Verification Test Pod Specifications

Each test pod runs once, attempts a single blocked connection with a 5-second timeout, and exits with code 0 (connection failed = isolation working = PASS) or code 1 (connection succeeded = isolation broken = FAIL).

| Test Pod | Namespace | From Label | Target | Expected Exit |
|----------|-----------|-----------|--------|---------------|
| `test-deny-ctfd` | challenges | `team=999, challenge=test-web` | `http://ctfd.ctfd.svc.cluster.local` | Non-zero (blocked) |
| `test-deny-cross-team` | challenges | `team=999` | `http://team-1-web-1-svc.challenges.svc.cluster.local` (pod labeled `team=1`) | Non-zero (blocked) |
| `test-deny-kube-api` | challenges | `team=999, challenge=test-web` | `https://kubernetes.default.svc.cluster.local` | Non-zero (blocked) |
| `test-deny-metadata` | challenges | `team=999, challenge=test-web` | `http://169.254.169.254/metadata/v1` | Non-zero (blocked) |

**Test pod security context**: Must comply with `restricted` PSS (same as challenge pods — UID 1000, runAsNonRoot, no privilege escalation, seccompProfile RuntimeDefault).

**Naming**: Test resources use `team_id=999` per constitution naming conventions.

---

## 5. Resource Relationships

```
Namespace: ctfd
  ServiceAccount: ctf-controller ──────────────────────────────────┐
  ServiceAccount: ctf-daemon ───────────────────────────────────────┤
                                                                     │ (RoleBinding.subjects)
Namespace: challenges                                                 │
  Role: ctf-controller ◄───────────────── RoleBinding: ctf-controller (subject: SA above)
  Role: ctf-daemon ◄──────────────────── RoleBinding: ctf-daemon    (subject: SA above)

Namespace: ingress-nginx
  Role: ctf-controller-nginx ◄────────── RoleBinding: ctf-controller-nginx (subject: ctf-controller SA)

NetworkPolicy flow (challenges namespace):
  [ingress-nginx pods] ──► challenge pods (ports 8080/1337/4444)
  challenge pods ──► [kube-system:53 DNS only]
  challenge pods ✗ ctfd namespace
  challenge pods ✗ other challenge pods
  challenge pods ✗ 10.96.0.1:443 (K8s API)
  challenge pods ✗ 169.254.169.254 (metadata)

NetworkPolicy flow (ctfd namespace):
  [ingress-nginx pods] ──► ctfd pods (port 8000)
  ctfd pods ──► mysql (3306), redis (6379), controller-api (5000)
  controller-api pods ──► challenges namespace (K8s API calls)
  controller-api pods ──► external 0.0.0.0/0:443
  all ctfd pods ──► kube-system:53 (DNS)
```
