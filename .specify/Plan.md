# InfoDays CTF — Infrastructure Project Specification

> **Version:** 2.0 (final, confirmed)
> **Status:** Ready for implementation
> **Methodology:** Spec-driven development via Spec Kit
> **Workflow per phase:** `/specify` → `/plan` → `/tasks` → `/implement`

---

## Table of Contents

1. [Event Identity](#1-event-identity)
2. [Architecture Overview](#2-architecture-overview)
3. [Infrastructure Decisions](#3-infrastructure-decisions)
4. [Challenge Design](#4-challenge-design)
5. [Flag Strategy](#5-flag-strategy)
6. [Pod Lifecycle](#6-pod-lifecycle)
7. [Resource Sizing](#7-resource-sizing)
8. [Phases Overview](#8-phases-overview)
9. [Phase 1 — Cluster & Networking Foundation](#phase-1--cluster--networking-foundation)
10. [Phase 2 — CTFd Platform Stack](#phase-2--ctfd-platform-stack)
11. [Phase 3 — Challenge Controller & Pod Lifecycle](#phase-3--challenge-controller--pod-lifecycle)
12. [Phase 4 — Challenge Base Images & DOCR](#phase-4--challenge-base-images--docr)
13. [Phase 5 — Network Hardening & Isolation](#phase-5--network-hardening--isolation)
14. [Phase 6 — Event Readiness & Runbook](#phase-6--event-readiness--runbook)
15. [Phase 7 — 100-Team Scaling (400 VUs)](#phase-7--100-team-scaling-400-vus)
16. [Time Estimates](#16-time-estimates)
17. [Risk Register](#17-risk-register)
18. [Glossary](#18-glossary)

---

## 1. Event Identity

| Field | Value |
|---|---|
| Event name | InfoDays CTF |
| Flag format | `infodays{...}` |
| Domain | `infodays.net` (already owned) |
| CTFd URL | `https://ctfd.infodays.net` |
| Instances dashboard | `https://ctfd.infodays.net` (via CTFd plugin — no separate URL) |
| Event duration | 12 hours |
| Audience | Closed — invited teams only |
| Teams | 20–50 baseline, up to 100 with Phase 7 scaling |
| Players per team | Max 4 — all sharing one CTFd team account |
| CTFd registration | Admin pre-creates all team accounts before event start |
| CTFd branding | TBD — default theme used until confirmed |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   Invited Teams (Internet)                       │
│             Browser · netcat · exploit scripts                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS / TCP
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│             DigitalOcean Load Balancer                           │
│      (auto-provisioned by DOKS via NGINX ingress)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                NGINX Ingress Controller                          │
│    HTTP/HTTPS routing · TCP passthrough (Pwn/Misc ports)        │
│    TLS termination via cert-manager + Let's Encrypt             │
└──────────┬──────────────────────────────────┬───────────────────┘
           │                                  │
┌──────────▼────────────┐        ┌────────────▼──────────────────┐
│  Namespace: ctfd       │        │  Namespace: challenges         │
│                        │        │                                │
│  CTFd   (5 replicas)   │        │  team-1-web-1   replicas=1    │
│  MySQL  (StatefulSet)  │        │  team-1-pwn-1   replicas=0    │
│  Redis                 │        │  team-1-misc-1  replicas=1    │
│  Controller API        │        │  team-2-web-1   replicas=0    │
│  Lifetime Daemon       │        │  team-2-pwn-1   replicas=1    │
│                        │        │  ...  (all pre-spawned)        │
│  PVC: db + uploads     │        └───────────────────────────────┘
└───────────────────────┘
           │
┌──────────▼────────────┐
│  DOCR (DigitalOcean   │
│  Container Registry)  │
│  Challenge images     │
│  Controller image     │
└───────────────────────┘

NetworkPolicy rules (strictly enforced):
  challenges → ctfd namespace         : BLOCKED
  challenges → other challenge pods   : BLOCKED
  challenges → Kubernetes API server  : BLOCKED
  challenges → DO metadata service    : BLOCKED
  ctfd → MySQL + Redis only           : ALLOWED
  ctfd controller → challenges ns     : ALLOWED (spawn/scale only)
  ingress → all services              : ALLOWED
  all pods → kube-dns UDP/TCP 53      : ALLOWED
```

---

## 3. Infrastructure Decisions

| Decision | Value | Rationale |
|---|---|---|
| Cloud provider | DigitalOcean | Selected after pricing comparison |
| Kubernetes | DOKS (DigitalOcean Managed Kubernetes) | Managed control plane, DO LB auto-provisioned |
| Provisioning | Terraform | Reproducible, state saved, easy to rebuild or tear down |
| Node pool | 5 × `s-4vcpu-8gb` | Scaled from 4 to 5 during load testing to support 50 teams — see §7 |
| Container registry | DigitalOcean Container Registry (DOCR) | Native DOKS integration — no imagePullSecret config needed |
| Ingress | NGINX Ingress Controller (Helm) | HTTP/HTTPS + TCP ConfigMap for Pwn/Misc port passthrough |
| TLS | cert-manager + Let's Encrypt | Auto-issuance and renewal on `infodays.net` |
| DNS | `infodays.net` (already owned) | `ctfd.infodays.net` → platform; `*.challenges.infodays.net` → instances |
| Alerting | **Postponed to v2** | Not in scope for v1 |
| Monitoring | **Postponed to v2** | Not in scope for v1 |
| Post-event cluster | TBD | Teardown script provided regardless of decision |

---

## 4. Challenge Design

### Categories and instance model

| Category | Live service? | Per-team pod | Flag type |
|---|---|---|---|
| Web | Yes | Yes | Derived (HMAC) |
| Pwn / Binary exploitation | Yes | Yes | Derived (HMAC) |
| Misc (TCP listener) | Yes | Yes | Derived (HMAC) |
| Crypto | No | No — file download | Static |
| Forensics | No | No — file download | Static |
| Reversing | No | No — file download | Static |
| OSINT | No | No — external research | Static |

### Challenge counts

| Category | Max challenges | Pods per team | Max pods (50 teams) | Max pods (100 teams) |
|---|---|---|---|---|
| Web | 5 | up to 5 | 250 | 500 |
| Pwn | 5 | up to 5 | 250 | 500 |
| Misc (TCP) | 5 | up to 5 | 250 | 500 |
| Crypto | 5 | 0 | 0 | 0 |
| Forensics | 5 | 0 | 0 | 0 |
| Reversing | 5 | 0 | 0 | 0 |
| OSINT | 5 | 0 | 0 | 0 |
| **Total** | **up to 35** | **up to 15/team** | **750 pods max** | **1,500 pods max** |

> **50 teams:** at most **200 pods Running** (50 × 4 active cap). The remaining 550 sit at `replicas=0`.
> **100 teams (Phase 7):** at most **400 pods Running** (100 × 4 active cap). The remaining 1,100 sit at `replicas=0`. Requires ProxySQL + dedicated MySQL node + larger node pool — see Phase 7.

### Instance URL format

- **Web:** `https://team-{id}-{challenge-id}.challenges.infodays.net`
- **Pwn / Misc:** `nc challenges.infodays.net {port}` — unique port per team per challenge via NGINX TCP ConfigMap
- Connection info shown **directly on the CTFd challenge page** by the CTFd plugin, after the team activates the instance

---

## 5. Flag Strategy

### Service-based challenges — derived flags

```
flag = infodays{ HMAC-SHA256(MASTER_SECRET, "{team_id}:{challenge_id}")[:32] }
```

```python
import hmac, hashlib, os

MASTER_SECRET = os.environ["CTF_MASTER_SECRET"]  # from K8s Secret, never hardcoded

def derive_flag(team_id: int, challenge_id: str) -> str:
    message = f"{team_id}:{challenge_id}".encode()
    digest = hmac.new(MASTER_SECRET.encode(), message, hashlib.sha256).hexdigest()[:32]
    return f"infodays{{{digest}}}"
```

**Properties:**
- Deterministic — same team + same challenge always produces the same flag
- One master secret controls the entire event; stored only in a K8s Secret, never in git
- Flag injected into pods as a K8s Secret env var `FLAG` — never baked into images
- CTFd receives all derived flags via import script before event start
- If master secret rotates, all flags change — use this to distinguish test vs production

### File-based challenges — static flags

- Set manually in CTFd at challenge creation time
- Format: `infodays{readable_string}`
- Same for all teams — no live service means no flag-stealing possible

---

## 6. Pod Lifecycle

### Pre-spawn — all pods created before event start

Admin runs `bulk_spawn.py` before the event. Every (team × service challenge) pair is created in the `challenges` namespace at `replicas=0`. Players experience zero spawn latency — no pod creation happens during the event.

### Active pod cap — 4 Running pods per team

- Each team may have at most **4 pods at `replicas=1`** (Running) simultaneously
- All other pods for that team exist at `replicas=0` (Suspended — zero CPU, zero RAM)
- Enforced by the controller before every activation: count Running pods labeled `team=<id>`
- If count = 4 → return error shown in CTFd plugin: *"You have 4 active instances. Stop one to continue."*

### Fixed lifetime — 60 minutes from activation

- Inactivity is **not tracked** — no sidecar, no connection counting, no complexity
- Instead: when a team activates a pod, the controller writes an annotation:
  `ctf/activated-at: <timestamp>`
- The lifetime daemon checks every 5 minutes:
  `if now - activated-at > 60 minutes → scale pod to replicas=0`
- Team sees the instance go Suspended on their challenge page
- Team clicks **Start** again to re-activate (same pod, same flag, instant — just `replicas=1`)

### Why scale to 0 instead of delete

| | Scale to 0 | Delete |
|---|---|---|
| Re-activate speed | Instant (replicas=1) | Slow — must recreate Deployment, Service, Secret, Ingress |
| Implementation | One API call | 8 API calls, duplicates bulk_spawn logic |
| Risk | Minimal | Re-creation can fail; flag Secret must be re-derived |
| etcd overhead | 750 lightweight objects | No difference |

**Scale to 0 is strictly better for v1. Delete only happens at end-of-event teardown.**

### Pod lifecycle state machine

```
[Suspended replicas=0] ◀──── lifetime daemon (60min) ────┐
        │                                                  │
   team clicks Start                               team clicks Stop
   (controller: replicas=1)                  (controller: replicas=0)
        │                                                  │
        ▼                                                  │
[Running replicas=1] ──────────────────────────────────────┘
        │
   end of event
        │
        ▼
[Deleted — teardown script]
```

### Lifetime extension (v1 simple approach)

If a team's pod is auto-suspended while they're actively working, they simply click Start again — the 60-minute timer resets from that moment. No "Extend" button needed in v1.

---

## 7. Resource Sizing

### Per-pod resource limits (challenge pods)

| Resource | Limit | Request |
|---|---|---|
| RAM | 128MB | 32MB |
| CPU | 0.5 cores | 0.1 cores |

> 128MB chosen over 256MB because at 50 teams × 4 running pods × 256MB = ~50GB which exceeds cluster capacity. At 128MB: 50 × 4 × 128MB = ~25GB — fits with headroom.
> If a specific challenge needs more RAM (e.g. heavy pwn binary), the manifest can override the limit per challenge individually.

### Platform resource limits (validated under 200-VU load testing)

| Component | CPU request | CPU limit | Memory request | Memory limit | Notes |
|---|---|---|---|---|---|
| CTFd (per replica) | 1000m | 2000m | 1536Mi | 2Gi | 4 gunicorn workers; OOM at 1536Mi under 200 VUs |
| MySQL 8 | — | 500m | — | 2Gi | max-connections=500, innodb-buffer-pool-size=512MB; OOM at 1Gi |
| Redis | — | 100m | — | 256Mi | Ephemeral, no persistence |
| Controller API | — | — | — | 512Mi | FastAPI + kubernetes client |
| Lifetime Daemon | — | — | — | 128Mi | Lightweight polling loop |

### Cluster RAM budget (worst case: 50 teams, 4 Running pods each)

| Workload | RAM per unit | Count | Total |
|---|---|---|---|
| Running challenge pods (replicas=1) | 128MB | 200 | ~25.6GB |
| Suspended challenge pods (replicas=0) | 0MB | 550 | 0GB |
| CTFd (5 replicas) | 2Gi | 5 | ~10GB |
| MySQL | 2Gi | 1 | ~2GB |
| Redis | 256MB | 1 | ~0.25GB |
| Controller API | 512Mi | 1 | ~0.5GB |
| Lifetime Daemon | 128Mi | 1 | ~0.13GB |
| NGINX Ingress | 256MB | 1 | ~0.25GB |
| Kube system overhead | — | — | ~2GB |
| **Total** | | | **~40.7GB** |

**Cluster capacity: 5 × 8GB = 40GB — tight fit at worst case.**

> The 200-pod worst case rarely occurs simultaneously. Real-world load testing showed stable operation at 200 VUs (50 teams × 4 members) with p95 ~10s and error rate <1%. The bottleneck is MySQL single-writer throughput, not RAM.

### Cluster RAM budget (Phase 7: 100 teams, 4 Running pods each)

| Workload | RAM per unit | Count | Total |
|---|---|---|---|
| Running challenge pods (replicas=1) | 128MB | 400 | ~51.2GB |
| Suspended challenge pods (replicas=0) | 0MB | 1,100 | 0GB |
| CTFd (10 replicas) | 2Gi | 10 | ~20GB |
| ProxySQL | 256MB | 2 | ~0.5GB |
| MySQL (dedicated node) | 12Gi | 1 | ~12GB |
| Redis | 256MB | 1 | ~0.25GB |
| Controller API | 512Mi | 1 | ~0.5GB |
| Lifetime Daemon | 128Mi | 1 | ~0.13GB |
| NGINX Ingress | 256MB | 1 | ~0.25GB |
| Kube system overhead | — | — | ~3GB |
| **Total** | | | **~87.8GB** |

**Phase 7 cluster capacity: 6 × s-8vcpu-16gb (general) + 1 × s-4vcpu-16gb (MySQL) = 96 + 16 = 112GB — fits with ~24GB headroom.**

> Alternatively: 8 × s-4vcpu-8gb (general) + 1 × s-4vcpu-16gb (MySQL) = 64 + 16 = 80GB — tight, would require reducing active cap from 4 to 3 or using fewer challenge categories.

### DigitalOcean cost estimate (50 teams — Phases 1–6)

| Resource | Unit cost | Event cost (12h) | Dev/test (2 days) |
|---|---|---|---|
| `s-4vcpu-8gb` × 5 nodes | ~$48/mo each | ~$4.80 | ~$16.00 |
| DO Load Balancer | ~$12/mo | ~$0.24 | ~$0.80 |
| DOCR Starter tier | $0/mo (free tier) | $0 | $0 |
| **Total** | | **~$5.04** | **~$16.80** |

**Estimated project cost (50 teams): ~$22–25.**

### DigitalOcean cost estimate (100 teams — Phase 7)

| Resource | Unit cost | Event cost (12h) | Dev/test (3 days) |
|---|---|---|---|
| `s-8vcpu-16gb` × 6 nodes (general) | ~$96/mo each | ~$11.52 | ~$57.60 |
| `s-4vcpu-16gb` × 1 node (MySQL) | ~$96/mo | ~$1.92 | ~$9.60 |
| DO Load Balancer | ~$12/mo | ~$0.24 | ~$1.20 |
| DOCR Starter tier | $0/mo (free tier) | $0 | $0 |
| **Total** | | **~$13.68** | **~$68.40** |

**Estimated project cost (100 teams): ~$82–90 including Phase 7 dev/testing.**

---

## 8. Phases Overview

| # | Phase | Key output | Depends on |
|---|---|---|---|
| 1 | Cluster & Networking Foundation | DOKS cluster, namespaces, NGINX, TLS, DOCR via Terraform | — |
| 2 | CTFd Platform Stack | CTFd live at `ctfd.infodays.net` | Phase 1 |
| 3 | Challenge Controller & Pod Lifecycle | Python controller, bulk spawn, lifetime daemon, CTFd plugin | Phase 1, 2 |
| 4 | Challenge Base Images & DOCR | Web/Pwn/Misc/Static base images pushed to DOCR | Phase 1 |
| 5 | Network Hardening & Isolation | NetworkPolicies, RBAC, LimitRange, PodSecurity | Phase 2, 3, 4 |
| 6 | Event Readiness & Runbook | Load test, pre-event checklist, operations runbook | All phases |
| 7 | 100-Team Scaling (400 VUs) | ProxySQL, dedicated MySQL node, CTFd scale-out, 400-VU validation | Phase 6 |

---

## Phase 1 — Cluster & Networking Foundation

### Objective

Provision the DOKS cluster and all supporting DigitalOcean resources via Terraform. Stand up NGINX ingress, cert-manager TLS, DOCR, namespace structure, and RBAC. No application workloads deployed in this phase.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 1: Cluster & Networking Foundation.

Provision all infrastructure via Terraform and deploy foundational Kubernetes resources.

Terraform resources to create:
  - DOKS cluster: region fra1 (Frankfurt — closest to Morocco), Kubernetes 1.29+
  - Node pool: 4 nodes, slug s-4vcpu-8gb, auto-scale min=3 max=5
  - DOCR: name infodays-registry, Starter tier
  - DOCR ↔ DOKS integration: digitalocean_container_registry_docker_credentials
    attached to the cluster (native DO integration — no imagePullSecret needed)
  - DO Firewall: allow inbound 80, 443, and TCP ports 30000-32767 (NodePort range for Pwn/Misc)
  - Terraform state: local backend for v1 (tfstate file, gitignored)
  - outputs.tf: cluster endpoint, kubeconfig, registry endpoint

Kubernetes resources (applied via kubectl after Terraform, using Helm where appropriate):

1. Namespaces: ctfd, challenges, monitoring
   ResourceQuota per namespace:
     ctfd:       4 CPU / 8Gi memory / 20 pods
     challenges: 40 CPU / 80Gi memory / 800 pods
   LimitRange in challenges namespace:
     default limit:   128Mi RAM / 0.5 CPU
     default request: 32Mi RAM / 0.1 CPU
     max per pod:     256Mi RAM / 1 CPU

2. RBAC: ServiceAccount + Role + RoleBinding for:
   - ctfd namespace: ctfd-app (read secrets, configmaps)
   - challenges namespace: challenge-controller (full CRUD on Deployments, Services,
     Secrets, Ingresses — used by controller running in ctfd namespace)
   - challenges namespace: challenge-daemon (get/list/patch Deployments only)

3. NGINX Ingress Controller via Helm (ingress-nginx chart):
   - TCP ConfigMap enabled (for Pwn/Misc port passthrough)
   - DO Load Balancer auto-provisioned
   - Helm values file: k8s/ingress/nginx-values.yaml

4. cert-manager via Helm:
   - ClusterIssuer: letsencrypt-prod (for infodays.net)
   - ClusterIssuer: letsencrypt-staging (for testing — avoids LE rate limits)

5. DNS records to create manually in DO DNS panel (document these):
   - ctfd.infodays.net          → DO Load Balancer IP (A record)
   - *.challenges.infodays.net  → DO Load Balancer IP (A record)

6. Post-deploy validation script (scripts/validate-cluster.sh):
   - kubectl get nodes → all Ready
   - kubectl get quota -A → ResourceQuotas present
   - curl https://ctfd.infodays.net → TLS responds (after CTFd deployed)
   - kubectl get clusterissuer → letsencrypt-prod Ready

Out of scope: CTFd app, challenge pods, controller, monitoring.
```

### Deliverables

- [ ] `terraform/main.tf` — DOKS cluster, node pool, DOCR, firewall
- [ ] `terraform/variables.tf` — do_token, region, cluster_name, node_count
- [ ] `terraform/outputs.tf` — kubeconfig, cluster endpoint, registry endpoint
- [ ] `terraform/versions.tf` — provider versions pinned
- [ ] `k8s/namespaces/` — namespace + ResourceQuota + LimitRange manifests
- [ ] `k8s/rbac/` — ServiceAccount, Role, RoleBinding per namespace
- [ ] `k8s/ingress/nginx-values.yaml` — NGINX Helm values
- [ ] `k8s/ingress/tcp-services-configmap.yaml` — TCP port mapping template
- [ ] `k8s/tls/clusterissuer-prod.yaml` — Let's Encrypt production
- [ ] `k8s/tls/clusterissuer-staging.yaml` — Let's Encrypt staging
- [ ] `docs/dns-setup.md` — DNS records to create in DO panel
- [ ] `scripts/validate-cluster.sh` — post-deploy health check
- [ ] `scripts/deploy-infra.sh` — `terraform apply` + `helm install` + `kubectl apply` in order

### Definition of Done

- [ ] `terraform apply` completes without errors, DOKS cluster visible in DO console
- [ ] All 3 namespaces present with correct ResourceQuotas and LimitRanges
- [ ] NGINX Ingress Controller running, DO Load Balancer IP assigned
- [ ] cert-manager issues a staging certificate on `ctfd.infodays.net` successfully
- [ ] DOCR reachable and `docker pull` works from a pod in `challenges` namespace
- [ ] `validate-cluster.sh` exits 0

---

## Phase 2 — CTFd Platform Stack

### Objective

Deploy CTFd, MySQL 8, and Redis in the `ctfd` namespace. CTFd must be live at `https://ctfd.infodays.net`. Admin pre-creates all team accounts via import script before the event.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 2: CTFd Platform Stack.

Deploy the CTFd application stack in the `ctfd` namespace.

CTFd URL: https://ctfd.infodays.net
Flag format: infodays{...}
Registration: disabled (admin pre-creates all teams)
Team mode: enabled (teams share one account, max 4 members)

Components:

1. CTFd Deployment
   - Image: ctfd/ctfd:latest
   - Replicas: 5 (scaled from 2 during 200-VU load testing)
   - All config via env vars (no baked config files):
       DATABASE_URL, REDIS_URL, SECRET_KEY, SERVER_SENT_EVENTS=false,
       WORKERS=4 (reduced from 8 — fewer workers per replica reduces per-pod memory and MySQL connections),
       REVERSE_PROXY=true, SESSION_COOKIE_SECURE=true, SESSION_COOKIE_HTTPONLY=true,
       MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAILFROM_ADDR
   - Liveness probe:  GET /healthcheck — initialDelaySeconds: 30, periodSeconds: 10
   - Readiness probe: GET /healthcheck — initialDelaySeconds: 10, periodSeconds: 5
   - Init container: busybox, runs: until nc -z mysql 3306; do sleep 2; done
   - Resource limits: 2Gi RAM / 2 CPU (request: 1536Mi / 1 CPU)

2. MySQL 8 StatefulSet
   - Replicas: 1
   - PVC: 10Gi, storageClassName: do-block-storage
   - Credentials from K8s Secret ctfd-secrets
   - Args: --max-connections=500 --innodb-buffer-pool-size=536870912 (512MB)
   - Resource limits: 2Gi RAM / 0.5 CPU (OOM-killed at 1Gi under 200 VU load)

3. Redis Deployment
   - Image: redis:7-alpine
   - Replicas: 1
   - No persistence
   - Resource limits: 256Mi RAM / 0.1 CPU

4. Kubernetes Secret (ctfd-secrets) — template only, values injected at deploy time:
   - MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD, SECRET_KEY,
     MAIL_PASSWORD, CTF_MASTER_SECRET (used by controller in Phase 3)

5. Services (all ClusterIP):
   - ctfd-service: port 80
   - mysql: port 3306
   - redis: port 6379

6. Ingress:
   - Host: ctfd.infodays.net → ctfd-service:80
   - TLS: cert-manager annotation, ClusterIssuer letsencrypt-prod

7. NetworkPolicy (ctfd namespace):
   - CTFd pods egress: allow MySQL:3306 and Redis:6379 within ctfd namespace only
   - CTFd pods ingress: allow from ingress-nginx namespace on port 80
   - MySQL ingress: allow from ctfd namespace only
   - Redis ingress: allow from ctfd namespace only
   - Default: deny all other ingress and egress

8. Admin setup script (scripts/setup-ctfd.sh):
   - Waits for CTFd to be ready (polls /healthcheck)
   - Configures via CTFd API:
       event name: "InfoDays CTF", team mode: on,
       registration: disabled, flag format: infodays{...},
       start/end time parameters

9. Team import script (scripts/import-teams.py):
   - Input: data/teams.csv (columns: team_name, email, password)
   - Creates each team via POST /api/v1/teams (CTFd admin API)
   - Prints summary: created / already exists / failed
   - data/teams-template.csv provided as starting point

Out of scope: challenge pods, controller, monitoring.
```

### Deliverables

- [ ] `k8s/ctfd/deployment.yaml`
- [ ] `k8s/ctfd/mysql-statefulset.yaml`
- [ ] `k8s/ctfd/redis-deployment.yaml`
- [ ] `k8s/ctfd/secrets.yaml` — template (gitignored when filled)
- [ ] `k8s/ctfd/services.yaml`
- [ ] `k8s/ctfd/ingress.yaml`
- [ ] `k8s/ctfd/networkpolicy.yaml`
- [ ] `scripts/setup-ctfd.sh`
- [ ] `scripts/import-teams.py`
- [ ] `data/teams-template.csv`

### Definition of Done

- [ ] CTFd reachable at `https://ctfd.infodays.net` with valid TLS certificate
- [ ] CTFd configured: team mode on, registration disabled, flag format `infodays{...}`
- [ ] MySQL data persists across CTFd pod restarts (verified by restart test)
- [ ] `import-teams.py` successfully creates 5 test teams
- [ ] NetworkPolicy blocks CTFd from reaching `challenges` namespace

---

## Phase 3 — Challenge Controller & Pod Lifecycle

### Objective

Build the Python challenge controller: bulk pre-spawn, team-triggered Start/Stop (scale replicas), fixed 60-minute lifetime daemon (scale to 0 after timeout), and a minimal CTFd plugin that shows Start/Stop buttons + instance URL on each challenge page. No persistent API server — the controller exposes a minimal FastAPI only for the CTFd plugin to call.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 3: Challenge Controller & Pod Lifecycle.

Language: Python 3.11+
K8s client: official `kubernetes` Python library
Namespace for pods: challenges
Namespace for controller: ctfd
Flag derivation: HMAC-SHA256(MASTER_SECRET, "{team_id}:{challenge_id}")[:32]
MASTER_SECRET: from env var CTF_MASTER_SECRET (K8s Secret ctfd-secrets)
Max Running pods per team: 4 (replicas=1 count)
Pod lifetime: 60 minutes from activation → scale to replicas=0
Daemon check interval: every 5 minutes
Spawn model: ALL pods pre-spawned at replicas=0 before event — no on-demand creation during event

Challenge manifest format (YAML):
  id: web-sqli
  name: "SQL Injection"
  category: web           # web | pwn | misc | crypto | forensics | reversing | osint
  image: registry.digitalocean.com/infodays-registry/web-sqli:latest
  port: 80
  type: http              # http → Ingress; tcp → NGINX TCP ConfigMap entry
  points: 100
  memory_limit: 128Mi     # optional override, defaults to LimitRange

Components:

1. Flag derivation (controller/flag.py):
   - derive_flag(team_id, challenge_id) → "infodays{...}"
   - CLI: python flag.py --team 3 --challenge web-sqli

2. Bulk pre-spawn script (controller/bulk_spawn.py):
   - Reads teams list from CTFd admin API + challenge manifests from challenges/manifests/
   - Skips file-based categories (crypto, forensics, reversing, osint)
   - For each (team_id, challenge manifest) where category in [web, pwn, misc]:
       Creates in challenges namespace:
       a) K8s Secret: name=team-{id}-{challenge-id}-secret
          data: FLAG=<derived_flag>
          labels: team={id}, challenge={id}, managed-by=ctf-controller
       b) K8s Deployment: name=team-{id}-{challenge-id}
          replicas=0 (suspended)
          image from manifest
          env: FLAG from secretKeyRef
          resource limits from manifest or LimitRange default
          annotation: ctf/activated-at="" (empty until activated)
          labels: team={id}, challenge={id}, managed-by=ctf-controller
       c) K8s Service: name=team-{id}-{challenge-id}-svc
          ClusterIP, port from manifest
          labels: team={id}, challenge={id}, managed-by=ctf-controller
       d) If type=http: Ingress rule → team-{id}-{challenge-id}.challenges.infodays.net
       e) If type=tcp: Add entry to NGINX TCP ConfigMap (unique port assigned from pool 30000+)
   - Idempotent: skip if resource already exists (safe to re-run)
   - Parallel: ThreadPoolExecutor(max_workers=10) for speed
   - Prints progress: "Spawned team-3-web-sqli" / "Skipped (exists)"

3. Controller FastAPI (controller/api.py):
   Minimal API — only called by the CTFd plugin. Not a full management system.
   Auth: X-Controller-Key header (shared secret from K8s Secret)

   POST /activate
     body: { team_id, challenge_id }
     - Count pods labeled team={id} AND replicas=1 in challenges namespace
     - If count >= 4: return 429 { error: "Max 4 active instances reached. Stop one to continue." }
     - Patch Deployment replicas=1
     - Write annotation ctf/activated-at: <now ISO timestamp>
     - Return 200 { status: "starting", url: "<instance URL or nc command>" }

   POST /deactivate
     body: { team_id, challenge_id }
     - Patch Deployment replicas=0
     - Clear annotation ctf/activated-at
     - Return 200 { status: "suspended" }

   GET /status/{team_id}
     - Returns list of all challenges for team with status:
       running (replicas=1) | suspended (replicas=0, activated-at set) |
       fresh (replicas=0, never activated) | unknown
     - Includes instance URL for running pods
     - Return 200 { challenges: [...] }

   GET /health
     - Returns 200 { status: "ok" }

4. Lifetime daemon (controller/daemon.py):
   - Runs as a separate Deployment in ctfd namespace (lightweight — 1 replica)
   - Loop every 5 minutes:
       List all Deployments in challenges namespace with label managed-by=ctf-controller
       For each Deployment where replicas=1:
         Read annotation ctf/activated-at
         If activated-at is set AND (now - activated-at) > 60 minutes:
           Patch replicas=0
           Clear ctf/activated-at annotation
           Log: "Auto-suspended team-{id}-{challenge-id} (lifetime exceeded)"

5. Flag import script (controller/import_flags.py):
   - For every (team, service-challenge) pair: derive flag
   - POST /api/v1/flags to CTFd admin API with team association
   - Run once after bulk_spawn, before event start

6. CTFd plugin (ctfd-plugin/):
   Minimal Python CTFd plugin — only adds UI elements to service challenge pages.
   No scoreboard changes, no flag validation changes — those stay vanilla CTFd.

   Plugin adds to each challenge page (web/pwn/misc only):
   - Status badge: Running (green) / Suspended (gray) / Fresh (gray)
   - If Fresh or Suspended: "▶ Start Instance" button
     → POST to controller /activate → refresh status
   - If Running: "⏹ Stop Instance" button + instance URL or nc command
     → POST to controller /deactivate → refresh status
   - Auto-refresh status every 15 seconds via JS fetch to controller /status/{team_id}
   - Team ID read from CTFd session (current team)
   - Controller URL and X-Controller-Key configured via CTFd admin config panel

   Plugin does NOT touch:
   - Flag submission logic
   - Score calculation
   - Other challenge categories (crypto, forensics, reversing, osint show normally)

7. Teardown script (scripts/teardown-challenges.sh):
   - Deletes all resources labeled managed-by=ctf-controller in challenges namespace
   - Used at end of event
   - Requires confirmation prompt before executing

Out of scope: Dockerfiles, network policies, monitoring.
```

### Deliverables

- [ ] `controller/flag.py`
- [ ] `controller/bulk_spawn.py`
- [ ] `controller/api.py` — FastAPI controller
- [ ] `controller/daemon.py` — lifetime daemon
- [ ] `controller/import_flags.py`
- [ ] `controller/requirements.txt`
- [ ] `controller/Dockerfile` — controller API image
- [ ] `controller/daemon.Dockerfile` — daemon image
- [ ] `k8s/controller/api-deployment.yaml` — controller FastAPI Deployment + Service
- [ ] `k8s/controller/daemon-deployment.yaml` — daemon Deployment
- [ ] `ctfd-plugin/__init__.py` — CTFd plugin entry point
- [ ] `ctfd-plugin/assets/plugin.js` — Start/Stop buttons + status polling
- [ ] `challenges/manifests/` — one YAML manifest per challenge (examples included)
- [ ] `challenges/manifests/schema.yaml` — documented manifest format
- [ ] `scripts/teardown-challenges.sh`

### Definition of Done

- [ ] `bulk_spawn.py` creates all K8s resources for 5 test teams × 3 test challenges — idempotent on re-run
- [ ] `/activate` scales a pod to replicas=1 and sets `ctf/activated-at` annotation
- [ ] `/deactivate` scales a pod to replicas=0
- [ ] 4-pod cap enforced — 5th activation returns 429 with correct error message
- [ ] Daemon scales a pod to replicas=0 after simulated 60-minute-old `ctf/activated-at`
- [ ] Re-activation after daemon suspend works immediately (replicas back to 1)
- [ ] CTFd plugin shows correct status badge and Start/Stop button on a test challenge page
- [ ] `import_flags.py` pushes all derived flags to CTFd API successfully

---

## Phase 4 — Challenge Base Images & DOCR

### Objective

Build working Dockerfile templates for all service challenge types and the static file builder. Push all base images to DOCR. Provide a push script for challenge authors.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 4: Challenge Base Images & DOCR.

Registry: registry.digitalocean.com/infodays-registry
Flag env var: FLAG (injected at runtime via K8s Secret — never baked into service images)
Flag format: infodays{...}

Build 4 base images:

1. Web challenge base (challenges/base-images/web/)
   - Multi-stage: builder (installs deps) → runtime (Alpine + Python 3.11)
   - Flask app example: login form vulnerable to SQL injection
     /flag route returns FLAG env var only after successful SQLi bypass
   - FLAG read from environment variable at runtime
   - Non-root user uid=1000, read-only filesystem, tmpfs on /tmp
   - Exposes port 80
   - Tag: registry.digitalocean.com/infodays-registry/base-web:latest

2. Pwn challenge base (challenges/base-images/pwn/)
   - Ubuntu 22.04
   - socat TCP listener on port 1337 → runs vulnerable C binary
   - Example binary (vuln.c): stack buffer overflow, prints FLAG after exploit
   - Compiled: gcc -fno-stack-protector -z execstack -no-pie -o vuln vuln.c
   - FLAG read from environment variable by the binary
   - Non-root user uid=1000
   - Exposes port 1337
   - Tag: registry.digitalocean.com/infodays-registry/base-pwn:latest

3. Misc TCP challenge base (challenges/base-images/misc/)
   - Alpine + Python 3.11
   - socat TCP listener on port 4444 → Python riddle script
   - Example puzzle: multi-step netcat riddle, FLAG returned on all correct answers
   - FLAG read from environment variable
   - Non-root user uid=1000
   - Exposes port 4444
   - Tag: registry.digitalocean.com/infodays-registry/base-misc:latest

4. Static challenge archive builder (challenges/base-images/static/)
   - Python Alpine, build-time only — produces a .zip artifact, not a running pod
   - FLAG passed as Docker build ARG (static challenges only — FLAG is fixed)
   - Output: challenge.zip for upload to CTFd files section
   - Usage: docker build --build-arg FLAG="infodays{...}" -o ./dist .

Security requirements for all service images:
   - USER 1000 (non-root)
   - COPY --chown=1000:1000
   - Multi-stage build — no build tools in final layer
   - Read-only filesystem where applicable

DOCR push script (scripts/push-challenge.sh):
   - Usage: ./push-challenge.sh <image-name> <path-to-dockerfile-dir> [tag]
   - tag defaults to latest
   - Builds, tags, pushes to registry.digitalocean.com/infodays-registry/<image-name>:<tag>
   - Prerequisites: doctl auth init + doctl registry login

DOCR setup script (scripts/setup-docr.sh):
   - Runs: doctl registry login
   - Verifies DOKS ↔ DOCR integration is active

Out of scope: actual puzzle content beyond minimal working examples, flag generation.
```

### Deliverables

- [ ] `challenges/base-images/web/Dockerfile`
- [ ] `challenges/base-images/web/app.py` — Flask SQLi example
- [ ] `challenges/base-images/pwn/Dockerfile`
- [ ] `challenges/base-images/pwn/vuln.c` — buffer overflow example
- [ ] `challenges/base-images/misc/Dockerfile`
- [ ] `challenges/base-images/misc/puzzle.py` — TCP riddle example
- [ ] `challenges/base-images/static/Dockerfile`
- [ ] `scripts/push-challenge.sh`
- [ ] `scripts/setup-docr.sh`

### Definition of Done

- [ ] All three service images build without errors
- [ ] Web image: Flask starts, `/flag` returns FLAG env var after SQLi bypass
- [ ] Pwn image: socat starts on 1337, FLAG readable after exploit
- [ ] Misc image: TCP listener on 4444, FLAG returned on correct answer
- [ ] All images pushed to DOCR and pullable from a pod in `challenges` namespace
- [ ] `push-challenge.sh` successfully builds and pushes a test image end-to-end

---

## Phase 5 — Network Hardening & Isolation

### Objective

Enforce complete network isolation. A player with RCE inside a challenge pod must not reach other teams, CTFd internals, or the Kubernetes API. Apply PodSecurityStandards and RBAC for the controller and daemon service accounts.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 5: Network Hardening & Isolation.

Namespaces: ctfd, challenges, ingress-nginx
Challenge pods labeled: team=<id>, challenge=<id>, managed-by=ctf-controller

Threat model: player achieves RCE in a challenge pod.
Must NOT be able to reach:
  - Other teams' pods (cross-team flag theft)
  - CTFd namespace (scoreboard manipulation, DB access)
  - Kubernetes API server (cluster takeover)
  - DO metadata service at 169.254.169.254 (credential theft)

Goals:

1. NetworkPolicies — challenges namespace:
   - Default deny ALL ingress and egress (baseline policy)
   - Allow ingress: from ingress-nginx namespace only, on the pod's specific port
   - Allow egress: kube-dns UDP+TCP port 53 only
   - Block egress: ctfd namespace CIDR
   - Block egress: Kubernetes API server (10.96.0.1:443 or cluster default)
   - Block egress: DO metadata service (169.254.169.254)
   - No pod-to-pod traffic within challenges namespace

2. NetworkPolicies — ctfd namespace:
   - Default deny ALL ingress and egress
   - Allow ingress: from ingress-nginx namespace on port 80 (CTFd + controller API)
   - Allow egress: MySQL:3306 within ctfd namespace
   - Allow egress: Redis:6379 within ctfd namespace
   - Allow egress to challenges namespace: controller only (patch Deployments)
   - Allow egress: port 443 external (Let's Encrypt ACME + DOCR image pulls)
   - Allow egress: kube-dns UDP+TCP 53

3. PodSecurityStandards (namespace labels):
   - challenges: enforce=restricted
   - ctfd: enforce=baseline

4. RBAC — challenge-controller ServiceAccount (runs in ctfd namespace):
   - Role in challenges namespace:
       create, get, list, update, patch, delete:
       Deployments, Services, Secrets, Ingresses, ConfigMaps
   - No permissions in ctfd namespace
   - No ClusterRole

5. RBAC — challenge-daemon ServiceAccount (runs in ctfd namespace):
   - Role in challenges namespace:
       get, list, watch: Deployments, Pods
       update, patch: Deployments (to set replicas=0)
   - No permissions in ctfd namespace
   - No ClusterRole

6. Verification test suite (tests/network-isolation/):
   Four test pod manifests, each runs a curl/nc command and expects timeout/refused:
   - test-deny-ctfd.yaml        → curl http://ctfd-service.ctfd.svc.cluster.local
   - test-deny-cross-team.yaml  → curl http://team-1-web-1-svc.challenges.svc.cluster.local
                                   (run from a pod labeled team=2)
   - test-deny-kube-api.yaml    → curl -k https://kubernetes.default.svc.cluster.local
   - test-deny-metadata.yaml    → curl http://169.254.169.254/metadata/v1

   scripts/run-isolation-tests.sh:
   - Applies each test pod, waits for completion, checks exit code
   - Prints PASS (connection blocked) or FAIL (connection succeeded) per test
   - Cleans up test pods after run

Out of scope: monitoring, DNS, image scanning.
```

### Deliverables

- [ ] `k8s/network-policies/challenges-default-deny.yaml`
- [ ] `k8s/network-policies/challenges-allow-ingress.yaml`
- [ ] `k8s/network-policies/challenges-allow-dns.yaml`
- [ ] `k8s/network-policies/ctfd-default-deny.yaml`
- [ ] `k8s/network-policies/ctfd-allow-internal.yaml`
- [ ] `k8s/network-policies/ctfd-allow-controller-egress.yaml`
- [ ] `k8s/pod-security/namespace-labels.yaml`
- [ ] `k8s/rbac/challenge-controller-rbac.yaml`
- [ ] `k8s/rbac/challenge-daemon-rbac.yaml`
- [ ] `tests/network-isolation/test-deny-ctfd.yaml`
- [ ] `tests/network-isolation/test-deny-cross-team.yaml`
- [ ] `tests/network-isolation/test-deny-kube-api.yaml`
- [ ] `tests/network-isolation/test-deny-metadata.yaml`
- [ ] `scripts/run-isolation-tests.sh`

### Definition of Done

- [ ] All 4 isolation tests PASS (connections blocked)
- [ ] `kubectl auth can-i --as=system:serviceaccount:ctfd:challenge-controller list pods -n ctfd` → `no`
- [ ] `kubectl auth can-i --as=system:serviceaccount:ctfd:challenge-daemon delete deployments -n challenges` → `no` (can only patch, not delete)
- [ ] A challenge pod exceeding 128Mi RAM is OOMKilled without affecting other pods
- [ ] PodSecurityStandards blocks `privileged: true` pod creation in `challenges`

---

## Phase 6 — Event Readiness & Runbook

### Objective

Run a load test, walk through the full pre-event checklist on the live cluster, and produce the event-day operations runbook. No monitoring stack — alerting is postponed to v2.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 6: Event Readiness & Runbook.

Note: Alerting and monitoring are postponed to v2 — do NOT include Prometheus,
Grafana, Alertmanager, or kube-state-metrics in this phase.

Load test tool: k6
Target SLA: p95 response time < 3 seconds, error rate < 1% at 200 concurrent VUs (50 teams × 4 members)
Domain: ctfd.infodays.net

Goals:

1. Load test script (tests/load/k6-ctf-scenario.js):
   Simulates 200 concurrent virtual users (50 teams × 4 members each) for 45 minutes.
   VU-to-team assignment: TEAMS[Math.floor((__VU - 1) / 4) % TEAMS.length]
   Login stagger: 1 second per team (spread 50 teams over 50 seconds to avoid login burst)
   Per VU scenario:
     a) GET /login                                 (extract CSRF nonce)
     b) POST /login                                (with team credentials + nonce)
     c) GET /challenges                            (challenge list — primary event action)
     d) POST /api/v1/challenges/attempt            (wrong flag submission)
     e) POST /api/v1/challenges/attempt            (correct flag submission)
     f) POST /controller-proxy/activate            (activate via CTFd proxy)
     g) GET /controller-proxy/status/{team_id}     (check instance status)
   Session management: CTFd session cookie re-injected each iteration (k6 clears session cookies)
   429 handling: login + flag submission 429s marked as expected (CTFd rate limiting)
   Thresholds:
     http_req_duration: p(95) < 3000
     http_req_failed: rate < 0.01
   Output: JSON summary → tests/load/results/

2. MySQL backup script (scripts/backup-mysql.sh):
   - kubectl exec into MySQL pod, runs mysqldump
   - Saves to: backups/ctfd-backup-{timestamp}.sql
   - Run before event start and after event end

3. Pre-event checklist (docs/pre-event-checklist.md):
   Infrastructure:
   - [ ] DOKS: all 5 nodes Ready (kubectl get nodes)
   - [ ] DO Load Balancer: IP assigned, DNS resolving
   - [ ] TLS certificate: valid, not expiring within 30 days
   - [ ] DOCR: all challenge images present (doctl registry repository list-tags)

   CTFd platform:
   - [ ] https://ctfd.infodays.net loads, TLS is valid
   - [ ] Admin login works
   - [ ] All team accounts created (import-teams.py ran successfully)
   - [ ] CTFd settings: team mode on, registration disabled, event times correct
   - [ ] Flag format infodays{...} configured

   Challenge infrastructure:
   - [ ] bulk_spawn.py ran successfully — all challenge pods exist in challenges namespace
   - [ ] import_flags.py ran — all derived flags present in CTFd
   - [ ] Sample end-to-end test: activate one Web, one Pwn, one Misc instance
   - [ ] Verify FLAG env var inside test pods matches CTFd stored flag
   - [ ] Sample flag submission through CTFd UI — accepted correctly
   - [ ] 4-pod cap verified: 5th activation returns correct error

   Security:
   - [ ] All 4 network isolation tests PASS (run-isolation-tests.sh)
   - [ ] Controller API reachable from CTFd plugin (GET /health → 200)
   - [ ] Controller API rejects requests without X-Controller-Key header (→ 401)

   Ops readiness:
   - [ ] MySQL backup taken: scripts/backup-mysql.sh
   - [ ] Load test passed: p95 < 3s, error rate < 1% at 200 VUs (50 teams × 4 members)
   - [ ] Runbook reviewed by at least one team member
   - [ ] Teardown command tested in staging (not production)

4. Event-day runbook (docs/event-day-runbook.md):
   Section: Before opening
   - Commands to verify all systems green
   - How to open the event in CTFd (set start time or click Start)

   Section: During the event — common operations
   - Add a new challenge mid-event:
       build image → push-challenge.sh → add manifest → bulk_spawn.py --challenge <id> only
   - Restart a broken team pod (manual):
       kubectl rollout restart deployment/team-{id}-{challenge-id} -n challenges
   - Force-suspend a team's pod (admin action):
       kubectl patch deployment/team-{id}-{challenge-id} -n challenges -p '{"spec":{"replicas":0}}'
   - Scale CTFd under unexpected load:
       kubectl scale deployment/ctfd -n ctfd --replicas=3
   - Extend event end time: CTFd admin panel → Configuration → End time

   Section: End of event
   - Freeze scoreboard: CTFd admin panel → Freeze scores button
     (curl command alternative documented)
   - Announce winners
   - Export scores: CTFd admin → Export → CSV
   - Take final MySQL backup: scripts/backup-mysql.sh

   Section: Teardown
   - Destroy all challenge pods (keep CTFd):
       kubectl delete deployments,services,secrets,ingresses \
         -l managed-by=ctf-controller -n challenges
   - Full infrastructure teardown:
       cd terraform && terraform destroy
       (destroys DOKS cluster, node pool, load balancer, DOCR, firewall)
   - WARNING: terraform destroy is irreversible — confirm team decision first

Out of scope: alerting, monitoring dashboards — these are v2.
```

### Deliverables

- [ ] `tests/load/k6-ctf-scenario.js`
- [ ] `scripts/backup-mysql.sh`
- [ ] `docs/pre-event-checklist.md`
- [ ] `docs/event-day-runbook.md`

### Definition of Done

- [ ] Load test passes SLA: p95 < 3s, error rate < 1% at 200 concurrent VUs (50 teams × 4 members)
- [ ] Pre-event checklist completed end-to-end on the live cluster — all items checked
- [ ] MySQL backup script tested and produces a valid `.sql` file
- [ ] At least 3 runbook scenarios manually tested: force-suspend a pod, scale CTFd, teardown challenges

---

## 14b. Test Challenges — Platform & Flag Injection Validation

> **Purpose:** One minimal working challenge per category to verify the full pipeline end-to-end — image builds, flag injection via env var, pod lifecycle, CTFd plugin, and flag submission.
> These are not real event challenges. They are throwaway validation tools used during development and the pre-event dry run.
> **Rule for all service challenges:** read `FLAG` from `os.environ["FLAG"]` or `getenv("FLAG")` — never hardcode.

---

### Challenge naming convention for test challenges

| Field | Format | Example |
|---|---|---|
| Challenge ID | `test-{category}-1` | `test-web-1` |
| CTFd name | `[TEST] {Category} 1` | `[TEST] Web 1` |
| Points | 1 (so it doesn't affect scoring) | `1` |
| Team ID used | `999` (dedicated test team) | `team-999` |

---

### TC-1 — Web (service, derived flag)

**What it tests:** Flask image builds → FLAG injected via env → puzzle logic exposes FLAG → CTFd accepts submission

**Difficulty:** Trivial — the "puzzle" is a single hardcoded password check. The point is testing the pipeline, not the puzzle.

**Dockerfile** (`challenges/test-challenges/web/Dockerfile`):
```dockerfile
FROM python:3.11-alpine
RUN pip install flask --no-cache-dir
WORKDIR /app
COPY app.py .
RUN adduser -D -u 1000 ctf
USER 1000
EXPOSE 80
CMD ["python", "app.py"]
```

**app.py** (`challenges/test-challenges/web/app.py`):
```python
import os
from flask import Flask, request

app = Flask(__name__)
FLAG = os.environ["FLAG"]  # injected by K8s Secret at runtime

@app.route("/")
def index():
    return """
    <form method='POST' action='/login'>
      <input name='password' placeholder='password'/>
      <button type='submit'>Login</button>
    </form>
    """

@app.route("/login", methods=["POST"])
def login():
    # intentionally trivial — this is a pipeline test, not a real challenge
    if request.form.get("password") == "letmein":
        return f"Correct! Flag: {FLAG}"
    return "Wrong password.", 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
```

**Challenge manifest** (`challenges/manifests/test-web-1.yaml`):
```yaml
id: test-web-1
name: "[TEST] Web 1"
category: web
image: registry.digitalocean.com/infodays-registry/test-web-1:latest
port: 80
type: http
points: 1
```

**How to verify flag injection:**
```bash
# 1. Check FLAG is set inside the running pod
kubectl exec -n challenges deployment/team-999-test-web-1 -- env | grep FLAG
# Expected: FLAG=infodays{abcd1234...}

# 2. Verify it matches derived flag
python controller/flag.py --team 999 --challenge test-web-1
# Expected: infodays{abcd1234...}  ← must match above

# 3. Solve the puzzle and get the flag
curl -s -X POST http://<instance-url>/login -d "password=letmein"
# Expected: Correct! Flag: infodays{abcd1234...}

# 4. Submit via CTFd API and verify accepted
curl -s -X POST https://ctfd.infodays.net/api/v1/challenges/attempt \
  -H "Authorization: Token <team-token>" \
  -H "Content-Type: application/json" \
  -d '{"challenge_id": <ctfd-id>, "submission": "infodays{abcd1234...}"}'
# Expected: {"success": true, "data": {"status": "correct"}}
```

---

### TC-2 — Pwn (service, derived flag)

**What it tests:** Ubuntu image builds → socat listener → C binary reads FLAG from env → binary runs → CTFd accepts submission

**Difficulty:** Trivial — the "exploit" is just sending the correct input string. No real buffer overflow needed for the test challenge.

**vuln.c** (`challenges/test-challenges/pwn/vuln.c`):
```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main() {
    char *flag = getenv("FLAG");  // injected by K8s Secret at runtime
    char answer[32];

    printf("What is the magic word?\n> ");
    fflush(stdout);
    fgets(answer, sizeof(answer), stdin);
    answer[strcspn(answer, "\n")] = 0;  // strip newline

    // intentionally trivial check — pipeline test only
    if (strcmp(answer, "please") == 0) {
        printf("Here you go: %s\n", flag);
    } else {
        printf("Nope.\n");
    }
    return 0;
}
```

**Dockerfile** (`challenges/test-challenges/pwn/Dockerfile`):
```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y socat gcc --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY vuln.c .
RUN gcc -o vuln vuln.c && chmod +x vuln
RUN useradd -m -u 1000 ctf
USER 1000
EXPOSE 1337
CMD ["socat", "TCP-LISTEN:1337,reuseaddr,fork", "EXEC:./vuln"]
```

**Challenge manifest** (`challenges/manifests/test-pwn-1.yaml`):
```yaml
id: test-pwn-1
name: "[TEST] Pwn 1"
category: pwn
image: registry.digitalocean.com/infodays-registry/test-pwn-1:latest
port: 1337
type: tcp
points: 1
```

**How to verify flag injection:**
```bash
# 1. Check FLAG is set inside the running pod
kubectl exec -n challenges deployment/team-999-test-pwn-1 -- env | grep FLAG
# Expected: FLAG=infodays{efgh5678...}

# 2. Solve via netcat
echo "please" | nc <challenges.infodays.net> <assigned-port>
# Expected: Here you go: infodays{efgh5678...}

# 3. Verify it matches derived flag
python controller/flag.py --team 999 --challenge test-pwn-1
# Expected: infodays{efgh5678...}  ← must match above
```

---

### TC-3 — Misc TCP (service, derived flag)

**What it tests:** Alpine + socat → Python TCP script → FLAG from env → multi-step interaction → CTFd accepts submission

**puzzle.py** (`challenges/test-challenges/misc/puzzle.py`):
```python
import os, sys

FLAG = os.environ["FLAG"]  # injected by K8s Secret at runtime

def main():
    sys.stdout.write("Welcome to the InfoDays number game!\n")
    sys.stdout.write("Step 1: What is 6 x 7?\n> ")
    sys.stdout.flush()

    a1 = sys.stdin.readline().strip()
    if a1 != "42":
        sys.stdout.write("Wrong. Goodbye.\n")
        return

    sys.stdout.write("Step 2: What language is this service written in?\n> ")
    sys.stdout.flush()

    a2 = sys.stdin.readline().strip().lower()
    if a2 != "python":
        sys.stdout.write("Wrong. Goodbye.\n")
        return

    sys.stdout.write(f"Correct! Here is your flag: {FLAG}\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
```

**Dockerfile** (`challenges/test-challenges/misc/Dockerfile`):
```dockerfile
FROM python:3.11-alpine
RUN apk add --no-cache socat
WORKDIR /app
COPY puzzle.py .
RUN adduser -D -u 1000 ctf
USER 1000
EXPOSE 4444
CMD ["socat", "TCP-LISTEN:4444,reuseaddr,fork", \
     "EXEC:python /app/puzzle.py,pty,stderr"]
```

**Challenge manifest** (`challenges/manifests/test-misc-1.yaml`):
```yaml
id: test-misc-1
name: "[TEST] Misc 1"
category: misc
image: registry.digitalocean.com/infodays-registry/test-misc-1:latest
port: 4444
type: tcp
points: 1
```

**How to verify flag injection:**
```bash
# Solve interactively
nc <challenges.infodays.net> <assigned-port>
# > 42
# > python
# Expected: Correct! Here is your flag: infodays{ijkl9012...}
```

---

### TC-4 — Crypto (file-based, static flag)

**What it tests:** Static file delivery via CTFd → player downloads file → solves offline → submits static flag

**No pod, no image, no injection needed.** The flag is set manually in CTFd.

**Challenge file** (`challenges/test-challenges/crypto/challenge.txt`):
```
InfoDays CTF — [TEST] Crypto 1

This message has been encoded. Decode it to find the flag.

Encoded: aW5mb2RheXN7dGVzdF9jcnlwdG9fZmxhZ30=

Hint: This is a very common encoding. Not encryption.
```

> The encoded string decodes to `infodays{test_crypto_flag}` — trivial Base64.
> Static flag set in CTFd admin: `infodays{test_crypto_flag}`

**How to add to CTFd:**
```
CTFd Admin → Challenges → New Challenge
  Name:     [TEST] Crypto 1
  Category: crypto
  Value:    1
  Flag:     infodays{test_crypto_flag}   ← static, same for all teams
  Files:    upload challenge.txt
```

---

### TC-5 — Forensics (file-based, static flag)

**What it tests:** File upload in CTFd → player downloads → static flag submission

**Challenge file** (`challenges/test-challenges/forensics/image.png`):

A standard PNG with the flag hidden in the EXIF metadata or just appended as a comment string. Generated at build time with:

```bash
# Create a trivial PNG with flag in EXIF comment
convert -size 100x100 xc:white \
  -set comment "infodays{test_forensics_flag}" \
  challenges/test-challenges/forensics/image.png

# Player extracts it with:
exiftool image.png | grep Comment
# or: strings image.png | grep infodays
```

Static flag set in CTFd: `infodays{test_forensics_flag}`

---

### TC-6 — Reversing (file-based, static flag)

**What it tests:** Binary file upload → player downloads and reverse engineers → static flag submission

**Binary** (`challenges/test-challenges/reversing/check`):

```c
// check.c — compile to binary and upload to CTFd
#include <stdio.h>
#include <string.h>

int main() {
    char input[64];
    // flag is visible via strings command — trivial reversing test
    char flag[] = "infodays{test_reversing_flag}";

    printf("Enter the flag: ");
    scanf("%63s", input);

    if (strcmp(input, flag) == 0) {
        printf("Correct!\n");
    } else {
        printf("Wrong.\n");
    }
    return 0;
}
```

```bash
# Compile
gcc -o check check.c

# Player solves with:
strings check | grep infodays
# Output: infodays{test_reversing_flag}
```

Static flag set in CTFd: `infodays{test_reversing_flag}`

---

### TC-7 — OSINT (no file, static flag)

**What it tests:** CTFd challenge creation → external research task → static flag submission

**Challenge description in CTFd:**
```
[TEST] OSINT 1

Find the year DigitalOcean was founded.

Flag format: infodays{YYYY}
```

Static flag set in CTFd: `infodays{2011}`

No file, no pod, no image. Just a CTFd challenge entry.

---

### Full pipeline verification checklist

Run this after deploying all test challenges to verify the entire system works before the real event challenges are added.

```bash
# 1. Bulk spawn test challenges for test team 999
python controller/bulk_spawn.py --team 999

# 2. Import flags into CTFd for test team 999
python controller/import_flags.py --team 999

# 3. Verify each service pod exists at replicas=0
kubectl get deployments -n challenges -l team=999
# Expected: team-999-test-web-1, team-999-test-pwn-1, team-999-test-misc-1
#           all showing 0/0 READY

# 4. Activate web instance via controller
curl -X POST http://localhost:8000/activate \
  -H "X-Controller-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"team_id": 999, "challenge_id": "test-web-1"}'
# Expected: {"status": "starting", "url": "https://team-999-test-web-1.challenges.infodays.net"}

# 5. Verify pod is running
kubectl get deployment team-999-test-web-1 -n challenges
# Expected: READY 1/1

# 6. Verify FLAG inside pod matches derived flag
kubectl exec -n challenges deployment/team-999-test-web-1 -- env | grep FLAG
python controller/flag.py --team 999 --challenge test-web-1
# Both must output the same value

# 7. Solve the web challenge and get the flag
curl -X POST https://team-999-test-web-1.challenges.infodays.net/login \
  -d "password=letmein"
# Expected: Correct! Flag: infodays{...}

# 8. Submit to CTFd and verify accepted
# (use test team 999 session token)

# 9. Verify Pwn and Misc the same way

# 10. Verify static challenges (crypto, forensics, reversing, osint)
# Submit their static flags via CTFd — must be accepted

# 11. Test 4-pod cap
# Activate test-web-1, test-pwn-1, test-misc-1, and one more → 4 running
# Try to activate a 5th → must return 429

# 12. Test daemon suspension
# Manually set activated-at to 61 minutes ago on one pod
# Wait one daemon cycle (5 min) → pod must be at replicas=0

# 13. Test re-activation after suspension
# Click Start again on the suspended pod
# Must return to replicas=1 with the same flag
```

---

### Test challenge directory structure

```
challenges/
└── test-challenges/
    ├── web/
    │   ├── Dockerfile
    │   └── app.py
    ├── pwn/
    │   ├── Dockerfile
    │   └── vuln.c
    ├── misc/
    │   ├── Dockerfile
    │   └── puzzle.py
    ├── crypto/
    │   └── challenge.txt
    ├── forensics/
    │   └── image.png          (generated by build script)
    ├── reversing/
    │   ├── check.c
    │   └── check              (compiled binary)
    └── README.md              (instructions for running the full pipeline verification)

challenges/manifests/
    ├── test-web-1.yaml
    ├── test-pwn-1.yaml
    └── test-misc-1.yaml
```

---

## Phase 7 — 100-Team Scaling (400 VUs)

### Objective

Scale the platform from 50 teams (200 VUs) to 100 teams (400 VUs — 4 members per team). Current bottleneck is MySQL single-writer throughput: 200 VUs produce p95 ~10s latency because 5 CTFd replicas × 4 workers = 20 persistent MySQL connections competing for row locks. At 400 VUs this doubles to 40 connections with proportionally worse contention. The primary fix is ProxySQL connection pooling between CTFd and MySQL, combined with a dedicated MySQL node and scaled-out CTFd replicas.

### Background — Load test results (Phase 6, 200 VUs)

| Run | CTFd replicas | Workers | MySQL mem | p95 (ms) | Error rate | Status |
|---|---|---|---|---|---|---|
| 1 | 3 | 8 | 1Gi | 13,920 | 1.96% | FAIL |
| 2 | 5 | 8 | 2Gi | 17,540 | 3.31% | FAIL (MySQL OOM) |
| 3 | 5 | 4 | 2Gi | 8,850 | 0.40% | Error OK, p95 FAIL |
| 4 | 5 | 4 | 2Gi (1s stagger) | 9,970 | 0.39% | Error OK, p95 FAIL |

Root cause analysis: MySQL is the single point of serialization. More CTFd workers/replicas without connection pooling worsens contention. Reducing workers from 8→4 improved error rate (fewer OOM kills) but p95 remained ~10s.

### Spec Kit `/specify` prompt

```
/specify
Project: InfoDays CTF on DigitalOcean — Phase 7: 100-Team Scaling (400 VUs).

Current state: 5 × s-4vcpu-8gb nodes, 5 CTFd replicas (4 workers each), MySQL 8 single
instance (2Gi, max-connections=500, innodb-buffer-pool-size=512MB). At 200 VUs: p95 ~10s,
error rate <1%. Target: p95 < 3s, error rate < 1% at 400 VUs (100 teams × 4 members).

Problem: MySQL single-writer bottleneck. 20 persistent connections (5 replicas × 4 workers)
contending for row locks on CTFd's submissions, tracking, and session tables.

Goals:

1. ProxySQL connection pooler (primary fix):
   - Deploy ProxySQL as a Deployment (2 replicas) in ctfd namespace
   - Image: proxysql/proxysql:2.x
   - Multiplexing mode: pool ~50 server connections serving 400+ client connections
   - CTFd DATABASE_URL changes from mysql+pymysql://ctfd:pass@mysql/ctfd
     to mysql+pymysql://ctfd:pass@proxysql/ctfd
   - ProxySQL config:
       mysql_servers: mysql.ctfd.svc.cluster.local:3306
       mysql_users: ctfd (same credentials as direct connection)
       mysql_query_rules: route all to single writer (no read replicas in v1)
       max_connections: 50 (server-side)
       multiplexing: enabled
       connection_pool_size: 50
   - Health check: ProxySQL admin interface on port 6032
   - Resource limits: 256Mi RAM / 0.25 CPU per replica

2. Dedicated MySQL node (isolation):
   - Add a new node pool: 1 × s-4vcpu-16gb (16GB RAM for MySQL)
   - Taint: workload=mysql:NoSchedule
   - MySQL StatefulSet: add toleration + nodeSelector for the dedicated node
   - Increase MySQL resource limits: 12Gi RAM / 2 CPU
   - Increase innodb-buffer-pool-size to 8GB (rule of thumb: 50-70% of available RAM)
   - max-connections=1000

3. CTFd scale-out:
   - Increase replicas from 5 to 8-10
   - Workers stay at 4 per replica (ProxySQL handles connection pooling)
   - Resource limits unchanged (2Gi / 2 CPU per replica)
   - Consider anti-affinity rules to spread across nodes

4. Node pool scaling:
   - General pool: increase from 5 to 6 × s-4vcpu-8gb (or switch to s-8vcpu-16gb)
   - MySQL pool: 1 × s-4vcpu-16gb (dedicated, tainted)
   - Total: 7 nodes

5. Challenge pod scaling:
   - 100 teams × 15 service challenges × replicas=0 = 1500 Deployments (etcd pressure)
   - 100 teams × 4 active cap = 400 Running pods × 128MB = ~51.2GB
   - General pool must have enough RAM: 6 × 8GB = 48GB minus platform = ~35GB available
   - May need to increase to s-8vcpu-16gb nodes (6 × 16GB = 96GB)
   - OR reduce max challenges or active cap

6. TCP port mapping at scale:
   - Up to 10 TCP challenges (5 pwn + 5 misc) per team
   - 100 teams × 10 TCP challenges = 1,000 unique NodePorts (30000-30999)
   - 50 teams × 10 TCP challenges = 500 unique NodePorts — already exceeds DO LB 40-rule limit
   - DO Load Balancer 40 forwarding-rule limit means LB CANNOT forward TCP challenge ports
   - Current workaround (already in use): NodePort services with direct node IP access
   - CTFd plugin shows node IP:port for TCP challenges (not domain:port via LB)
   - NodePort range 30000-32767 provides ample room (2,767 ports available)
   - Firewall must allow inbound on NodePort range (already configured in Phase 1)
   - At 1,000 ports, etcd pressure from Service objects is moderate — monitor etcd latency
   - Alternative for HA: deploy HAProxy/Envoy DaemonSet for TCP load balancing across nodes

7. Updated load test (tests/load/k6-ctf-scenario.js):
   - Scale to 400 VUs, 100 teams, 45 minutes
   - Team assignment: TEAMS[Math.floor((__VU - 1) / 4) % TEAMS.length]
   - Stagger: 1s per team (100 teams → 100 second ramp)
   - Same thresholds: p95 < 3s, error rate < 1%

8. CiliumNetworkPolicy for controller → kube-apiserver:
   - Persist the currently cluster-applied CiliumNetworkPolicy to a YAML file
   - Required on DOKS where standard NetworkPolicy cannot target kube-apiserver
   - Also persist the ClusterRole/ClusterRoleBinding for node listing

Out of scope: MySQL read replicas, Redis clustering, CDN, monitoring/alerting.
```

### Deliverables

- [ ] `k8s/ctfd/proxysql-deployment.yaml` — ProxySQL Deployment + Service + ConfigMap
- [ ] `k8s/ctfd/proxysql-configmap.yaml` — ProxySQL configuration
- [ ] `infra/terraform/mysql-node-pool.tf` — Dedicated MySQL node pool with taint
- [ ] `k8s/ctfd/mysql-statefulset.yaml` — Updated with toleration, nodeSelector, increased resources
- [ ] `k8s/ctfd/deployment.yaml` — Updated DATABASE_URL to point at ProxySQL, scaled replicas
- [ ] `k8s/controller/cilium-networkpolicy.yaml` — Persisted CiliumNetworkPolicy for kube-apiserver access
- [ ] `k8s/controller/cluster-rbac.yaml` — Persisted ClusterRole/ClusterRoleBinding for node listing
- [ ] `tests/load/k6-ctf-scenario.js` — Updated for 400 VUs / 100 teams
- [ ] Updated `docs/pre-event-checklist.md` — 100-team specific checks
- [ ] Updated `docs/event-day-runbook.md` — ProxySQL operations, node pool management

### Definition of Done

- [ ] 400-VU load test passes: p95 < 3s, error rate < 1% over 45 minutes
- [ ] ProxySQL dashboard shows connection multiplexing working (50 server connections serving 400+ clients)
- [ ] MySQL runs on dedicated node with 12Gi+ available memory
- [ ] All 100 team accounts can log in and submit flags concurrently
- [ ] TCP challenge ports accessible via NodePort (bypassing LB 40-rule limit)
- [ ] CiliumNetworkPolicy and ClusterRole persisted in git (not just cluster-applied)

---

## 16. Time Estimates

| Phase | With Claude Code + Spec Kit |
|---|---|
| Phase 1 — Cluster & Networking | 1–2 hours |
| Phase 2 — CTFd Platform Stack | 2–3 hours |
| Phase 3 — Controller & Lifecycle | 4–5 hours |
| Phase 4 — Base Images & DOCR | 2–3 hours |
| Phase 5 — Network Hardening | 1–2 hours |
| Phase 6 — Event Readiness & Runbook | 1–2 hours |
| Phase 7 — 100-Team Scaling | 3–5 hours |
| **Total implementation** | **~14–22 hours** |
| Manual testing, dry run, challenge content | ~4–6 hours |
| **Full project** | **~3–4 working days** |

> DO infrastructure cost during dev/testing (~3 days): ~$17.
> Event day (12 hours): ~$5.
> **Total estimated cost: ~$22–25.**

---

## 17. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 50 teams × 4 running pods approaches cluster RAM limit | Medium | High | 5 nodes × 8GB = 40GB; challenge pods use 128MB each — 200 pods = ~25.6GB; platform stack uses ~13GB; tight but fits |
| MySQL OOM under concurrent load | High | Critical | **Validated:** MySQL OOM-killed at 1Gi with 200 VUs. Fixed: 2Gi limit, max-connections=500, innodb-buffer-pool-size=512MB. For 100 teams: Phase 7 adds ProxySQL connection pooling |
| CTFd OOM under concurrent load | Medium | High | **Validated:** CTFd OOM at 1536Mi with 8 workers. Fixed: 2Gi limit, 4 workers per replica, 5 replicas |
| CTFd plugin breaks CTFd entirely | Medium | Critical | Plugin is read-only except for Start/Stop API calls — no CTFd internals modified; tested in Phase 6 dry run |
| ctf/activated-at annotation not set (daemon skips pod) | Low | Low | Daemon only suspends pods with annotation set — worst case pod runs slightly longer |
| Player achieves container escape | Low | Critical | PodSecurityStandards restricted + full NetworkPolicy (Phase 5) |
| Player reaches CTFd internals via internal network | Low | High | NetworkPolicy blocks challenges→ctfd; unique flags limit blast radius to one team |
| MySQL data loss mid-event | Low | Critical | do-block-storage PVC (durable), pre-event backup, backup script in runbook |
| Master secret in git | Low | Critical | ctfd-secrets.yaml gitignored; secret only exists in K8s; documented in runbook |
| NGINX TCP ConfigMap port conflicts (Pwn/Misc) | Medium | Medium | Ports allocated sequentially from 30000+ — **must be generated sequentially** (race condition validated: parallel generation produced 43/100 entries). Single-threaded Python generator + single kubectl patch |
| DO Load Balancer 40 forwarding-rule limit | High | High | Each TCP challenge port uses one LB forwarding rule. Up to 10 TCP challenges (5 pwn + 5 misc) × 50 teams = 500 rules; at 100 teams = 1,000 rules. **Already exceeded at 50 teams.** Current workaround: NodePort services with direct node IP access bypass the LB entirely for TCP traffic. NGINX TCP ConfigMap still used for port mapping but LB only forwards HTTP/HTTPS. |
| cert-manager rate limit hit during testing | Medium | Low | Use letsencrypt-staging ClusterIssuer for all tests; switch to prod only for event |
| Team count exceeds 50 — scales to 100 teams | Medium | High | Phase 7 plan: ProxySQL, dedicated MySQL node, 8-10 CTFd replicas, larger nodes. Requires infrastructure changes |
| p95 latency exceeds 3s under full 200-VU load | High | Medium | **Validated:** p95 ~10s at 200 VUs with current stack. Root cause: MySQL single-writer bottleneck. Phase 7 ProxySQL connection pooling expected to reduce to <3s |
| bulk_spawn.py partial failure (some pods not created) | Medium | Medium | Script is idempotent — safe to re-run; prints clear created/skipped/failed per pod |
| Controller FastAPI crashes during event | Low | Medium | Pods keep running independently — only Start/Stop/status affected; restart is instant |
| CTFd token auth fails silently (302 redirect) | Medium | Medium | **Validated:** CTFd requires `Content-Type: application/json` on ALL requests using token auth, including GETs. Fixed in import_flags.py |

---

## 18. Glossary

| Term | Definition |
|---|---|
| CTFd | Open-source CTF platform — scoreboard, auth, challenge management, flag submission |
| DOKS | DigitalOcean Managed Kubernetes — managed control plane, native DO LB and DOCR integration |
| DOCR | DigitalOcean Container Registry — private image registry, no imagePullSecret needed with DOKS |
| Spec Kit | Spec-driven development toolkit — `specify → plan → tasks → implement` cycle with Claude Code |
| Pre-spawn | All challenge pods created at `replicas=0` by admin before event — zero spawn latency during event |
| Suspended pod | Deployment with `replicas=0` — exists in K8s, consumes zero CPU and RAM |
| Running pod | Deployment with `replicas=1` — actively serving, counts toward 4-pod cap |
| Active pod cap | Max 4 pods per team at `replicas=1` simultaneously — enforced by controller before every activation |
| Fixed lifetime | Pod activated at T is auto-suspended at T+60min regardless of activity — tracked via `ctf/activated-at` annotation |
| Lifetime daemon | Python process checking every 5 minutes — scales to 0 any pod whose lifetime has expired |
| Derived flag | `infodays{HMAC-SHA256(secret, team_id:challenge_id)[:32]}` — deterministic, same inputs = same flag always |
| Static flag | Fixed string set manually in CTFd — used for file-based challenges (crypto, forensics, reversing, osint) |
| CTFd plugin | Minimal Python plugin that adds Start/Stop buttons and status badge to service challenge pages |
| Controller API | FastAPI service in ctfd namespace — called only by CTFd plugin for activate/deactivate/status |
| bulk_spawn.py | Pre-event script that creates all (team × service challenge) K8s resources at replicas=0 |
| import_flags.py | Pre-event script that pushes all derived flags to CTFd admin API |
| NetworkPolicy | K8s resource enforcing firewall rules between pods — default-deny in both namespaces |
| LimitRange | K8s resource setting default/max CPU and RAM per pod in a namespace |
| ResourceQuota | K8s resource capping total CPU, RAM, and pod count per namespace |
| PodSecurityStandards | K8s admission control enforcing pod security constraints (restricted profile on challenges) |
| HMAC | Hash-based Message Authentication Code — used for deterministic, unforgeable flag derivation |
| terraform destroy | Destroys all DO resources (cluster, nodes, LB, DOCR) — irreversible, requires explicit confirmation |