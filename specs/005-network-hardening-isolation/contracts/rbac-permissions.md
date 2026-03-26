# Contract: RBAC Permissions

**Feature**: 005-network-hardening-isolation
**Date**: 2026-03-26

This contract defines the authoritative permission matrix for the two service accounts introduced/completed in this phase. Implementations MUST match this matrix exactly — neither over-granting nor under-granting.

---

## Service Account: `ctf-controller`

**Namespace**: `ctfd`
**Used by**: controller API (`api.py`), bulk spawn (`bulk_spawn.py`)

### Permissions in `challenges` namespace

| API Group | Resource | Verbs | Rationale |
|-----------|----------|-------|-----------|
| `apps` | `deployments` | get, list, watch, create, update, patch, delete | Pre-spawn (create), activate/deactivate (patch replicas), teardown (delete) |
| `` (core) | `services` | get, list, create, update, patch, delete | Per-challenge Service object management |
| `` (core) | `secrets` | get, list, create, update, patch, delete | FLAG secret creation and rotation |
| `networking.k8s.io` | `ingresses` | get, list, create, update, patch, delete | Per-challenge Ingress rule management |

### Permissions in `ingress-nginx` namespace

| API Group | Resource | Verbs | Rationale |
|-----------|----------|-------|-----------|
| `` (core) | `configmaps` | get, patch | `tcp-services` ConfigMap for TCP passthrough (pwn/misc ports) |

### Explicit non-permissions (verified via `kubectl auth can-i`)

- `list pods -n ctfd` → **no**
- `get secrets -n ctfd` → **no**
- `delete deployments -n ctfd` → **no**
- Any ClusterRole binding → **none**

---

## Service Account: `ctf-daemon`

**Namespace**: `ctfd`
**Used by**: lifetime daemon (`daemon.py`)

### Permissions in `challenges` namespace

| API Group | Resource | Verbs | Rationale |
|-----------|----------|-------|-----------|
| `apps` | `deployments` | get, list, watch, update, patch | Poll all deployments, scale expired pods to replicas=0 |
| `` (core) | `pods` | get, list, watch | Check pod status for active instance counting |

### Explicit non-permissions (verified via `kubectl auth can-i`)

- `delete deployments -n challenges` → **no** (may only patch replicas)
- `create deployments -n challenges` → **no**
- `delete pods -n challenges` → **no**
- Any resource in `ctfd` namespace → **no**
- Any ClusterRole binding → **none**

---

## Verification Commands

```bash
# Controller checks
kubectl auth can-i list pods -n ctfd \
  --as=system:serviceaccount:ctfd:ctf-controller
# Expected: no

kubectl auth can-i patch deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-controller
# Expected: yes

kubectl auth can-i delete deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-controller
# Expected: yes

# Daemon checks
kubectl auth can-i delete deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: no

kubectl auth can-i patch deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: yes

kubectl auth can-i list pods -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: yes
```
