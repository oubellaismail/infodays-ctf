# Data Model: Challenge Controller & Pod Lifecycle

**Feature**: `003-challenge-controller-pod-lifecycle`
**Date**: 2026-03-24

---

## Entities

All persistent state lives in Kubernetes — there is no separate database. The
entities below describe the K8s objects that the controller reads and writes.

---

### 1. ChallengeManifest

**Source**: `challenges/manifests/*.yaml` files (read-only by controller)

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `id` | string | yes | Lowercase, hyphen-separated; e.g., `web-sqli` |
| `name` | string | yes | Human-readable display name |
| `category` | enum | yes | `web`, `pwn`, `misc`, `crypto`, `forensics`, `reversing`, `osint` |
| `image` | string | yes | Full DOCR image ref: `registry.digitalocean.com/infodays-registry/{id}:{tag}` |
| `port` | integer | yes | Container port (e.g., 80, 1337, 4444) |
| `type` | enum | yes | `http` → Ingress rule; `tcp` → NGINX TCP ConfigMap |
| `points` | integer | yes | Challenge points value (positive integer) |
| `memory_limit` | string | no | Override memory limit (e.g., `128Mi`); defaults to LimitRange |

**Service challenges**: `category` in `{web, pwn, misc}` → require a pod.
**File challenges**: `category` in `{crypto, forensics, reversing, osint}` → skipped by bulk_spawn.

**State transitions**: ChallengeManifest is read-only; no state transitions.

---

### 2. ManagedDeployment

**K8s kind**: `Deployment` in namespace `challenges`
**Created by**: `bulk_spawn.py`
**Managed by**: controller API + lifetime daemon (scale operations only; never deleted)

| Field | Source | Value |
|-------|--------|-------|
| `metadata.name` | naming convention | `team-{team_id}-{challenge_id}` |
| `metadata.namespace` | fixed | `challenges` |
| `metadata.labels.team` | bulk_spawn | `{team_id}` |
| `metadata.labels.challenge` | bulk_spawn | `{challenge_id}` |
| `metadata.labels.managed-by` | bulk_spawn | `ctf-controller` |
| `metadata.annotations["ctf/activated-at"]` | controller API | UTC ISO 8601 string or empty |
| `spec.replicas` | controller API / daemon | `0` (suspended) or `1` (active) |
| `spec.template.spec.containers[0].image` | manifest | DOCR image ref |
| `spec.template.spec.containers[0].env[FLAG]` | secretKeyRef | from `team-{id}-{challenge-id}-secret` |
| `spec.template.spec.resources.limits.cpu` | manifest or LimitRange | ≤ `0.5` |
| `spec.template.spec.resources.limits.memory` | manifest or LimitRange | ≤ `128Mi` |

**State transitions**:

```
         bulk_spawn.py
              │
              ▼
         FRESH (replicas=0, activated-at="")
              │
    POST /activate (cap < 4)
              │
              ▼
         ACTIVE (replicas=1, activated-at=<now>)
         │                    │
POST /deactivate    (now - activated-at) > 60 min
         │                    │ (daemon)
         ▼                    ▼
    SUSPENDED (replicas=0, activated-at cleared)
         │
    POST /activate (cap < 4)
         │
         ▼
         ACTIVE (replicas=1, activated-at=<now>)
```

**Derived status** (computed by controller, not stored):

| Status | Condition |
|--------|-----------|
| `fresh` | `spec.replicas == 0` AND `ctf/activated-at == ""` |
| `running` | `spec.replicas == 1` |
| `suspended` | `spec.replicas == 0` AND `ctf/activated-at != ""` |
| `unknown` | Deployment not found |

---

### 3. FlagSecret

**K8s kind**: `Secret` in namespace `challenges`
**Created by**: `bulk_spawn.py`

| Field | Value |
|-------|-------|
| `metadata.name` | `team-{team_id}-{challenge_id}-secret` |
| `metadata.namespace` | `challenges` |
| `metadata.labels.team` | `{team_id}` |
| `metadata.labels.challenge` | `{challenge_id}` |
| `metadata.labels.managed-by` | `ctf-controller` |
| `data.FLAG` | base64(`infodays{HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32]}`) |

**State transitions**: Created once at spawn time; never modified.

---

### 4. ChallengeService

**K8s kind**: `Service` in namespace `challenges`
**Type**: `ClusterIP`
**Created by**: `bulk_spawn.py`

| Field | Value |
|-------|-------|
| `metadata.name` | `team-{team_id}-{challenge_id}-svc` |
| `metadata.namespace` | `challenges` |
| `metadata.labels.team` | `{team_id}` |
| `metadata.labels.challenge` | `{challenge_id}` |
| `metadata.labels.managed-by` | `ctf-controller` |
| `spec.selector` | `{team: {team_id}, challenge: {challenge_id}}` |
| `spec.ports[0].port` | from manifest `port` field |

---

### 5. ChallengeIngress (HTTP type only)

**K8s kind**: `Ingress` in namespace `challenges`
**Created by**: `bulk_spawn.py` (only for manifests with `type: http`)

| Field | Value |
|-------|-------|
| `metadata.name` | `team-{team_id}-{challenge_id}-ingress` |
| `metadata.namespace` | `challenges` |
| `metadata.annotations["cert-manager.io/cluster-issuer"]` | `letsencrypt-prod` |
| `spec.ingressClassName` | `nginx` |
| `spec.rules[0].host` | `team-{team_id}-{challenge_id}.challenges.infodays.net` |
| `spec.rules[0].http.paths[0].backend.service.name` | `team-{team_id}-{challenge_id}-svc` |
| `spec.rules[0].http.paths[0].backend.service.port.number` | from manifest `port` |
| `spec.tls[0].hosts[0]` | `team-{team_id}-{challenge_id}.challenges.infodays.net` |
| `spec.tls[0].secretName` | `team-{team_id}-{challenge_id}-tls` |

---

### 6. TCPConfigMapEntry (TCP type only)

**K8s kind**: Entry in ConfigMap `tcp-services` in namespace `ingress-nginx`
**Created by**: `bulk_spawn.py` (only for manifests with `type: tcp`)

| ConfigMap key | ConfigMap value |
|---------------|-----------------|
| `"{external_port}"` | `"challenges/team-{team_id}-{challenge_id}-svc:{target_port}"` |

**Port assignment**: Sequential from pool starting at 30000. At spawn time,
`bulk_spawn.py` reads the current ConfigMap to find the highest assigned port,
then increments by 1 for each new TCP challenge.

---

### 7. ActivationRequest (API input)

**Used by**: `POST /activate`, `POST /deactivate`

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `team_id` | string | yes | Non-empty string; maps to K8s label `team={team_id}` |
| `challenge_id` | string | yes | Non-empty string; maps to K8s label `challenge={challenge_id}` |

---

### 8. StatusResponse (API output)

**Used by**: `GET /status/{team_id}`

| Field | Type | Description |
|-------|------|-------------|
| `challenges` | list | One entry per challenge for the team |
| `challenges[].challenge_id` | string | Challenge identifier |
| `challenges[].status` | enum | `running`, `suspended`, `fresh`, `unknown` |
| `challenges[].url` | string or null | Instance URL (HTTP) or `nc` command (TCP); null if not running |
| `challenges[].activated_at` | string or null | ISO 8601 UTC timestamp or null |

---

## Relationships

```
ChallengeManifest (1) ──► (N) ManagedDeployment   [one manifest → N team deployments]
ChallengeManifest (1) ──► (N) FlagSecret           [one manifest → N team secrets]
ChallengeManifest (1) ──► (N) ChallengeService     [one manifest → N team services]
ChallengeManifest (1) ──► (0..N) ChallengeIngress  [http type only]
ChallengeManifest (1) ──► (0..N) TCPConfigMapEntry [tcp type only]

ManagedDeployment (1) ──► (1) FlagSecret           [one deployment → one flag secret]
ManagedDeployment (1) ──► (1) ChallengeService     [one deployment → one service]
```

---

## LimitRange (namespace-level default)

Applied to the `challenges` namespace. Defines the default resource ceiling when
a manifest does not specify `memory_limit`.

| Resource | Default Limit | Default Request |
|----------|--------------|-----------------|
| CPU | `0.5` | `0.1` |
| Memory | `128Mi` | `32Mi` |

(Values from constitution Table § V.)
