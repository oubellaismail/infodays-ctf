# Data Model: CTFd Platform Stack

**Branch**: `002-ctfd-platform-stack` | **Date**: 2026-03-24

## Kubernetes Resource Graph

```
Namespace: ctfd
│
├── Secret: ctfd-secrets
│   Keys: MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD, MYSQL_DATABASE,
│         SECRET_KEY, MAIL_PASSWORD, CTF_MASTER_SECRET (reserved for Phase 3)
│   Consumed by: CTFd Deployment (env injection), MySQL StatefulSet (env injection)
│
├── StatefulSet: mysql
│   Image: mysql:8
│   Replicas: 1
│   ├── PersistentVolumeClaim: mysql-data (10 Gi, do-block-storage)
│   └── Service: mysql (ClusterIP, port 3306)
│       Consumed by: CTFd init container, CTFd Deployment (DATABASE_URL)
│
├── Deployment: redis
│   Image: redis:7-alpine
│   Replicas: 1
│   └── Service: redis (ClusterIP, port 6379)
│       Consumed by: CTFd Deployment (REDIS_URL)
│
└── Deployment: ctfd
    Image: ctfd/ctfd:latest
    Replicas: 2
    Init container: busybox (waits for mysql:3306)
    ├── Service: ctfd-service (ClusterIP, port 80 → targetPort 8000)
    │   Consumed by: Ingress
    └── Ingress: ctfd-ingress
        Host: ctfd.infodays.net → ctfd-service:80
        TLS: cert-manager / letsencrypt-prod ClusterIssuer
```

## Kubernetes Resource Specifications

### Secret: `ctfd-secrets`

| Key | Purpose | Source |
|-----|---------|--------|
| `MYSQL_ROOT_PASSWORD` | MySQL root user password | Operator-provided at deploy time |
| `MYSQL_PASSWORD` | CTFd application DB user password | Operator-provided at deploy time |
| `MYSQL_DATABASE` | Database name for CTFd | Fixed: `ctfd` |
| `SECRET_KEY` | CTFd Flask session signing key | Operator-provided (random 32+ bytes) |
| `MAIL_PASSWORD` | SMTP authentication password | Optional; leave empty if mail not needed |
| `CTF_MASTER_SECRET` | HMAC seed for flag derivation | Reserved for Phase 3 controller — DO NOT use in Phase 2 |

**Gitignore rule**: `k8s/ctfd/secrets.local.yaml` (file with real values) — never committed.

---

### StatefulSet: `mysql`

| Attribute | Value |
|-----------|-------|
| Image | `mysql:8` |
| Replicas | 1 |
| CPU limit | 0.5 |
| RAM limit | 1 Gi |
| PVC name | `mysql-data` |
| PVC size | 10 Gi |
| StorageClass | `do-block-storage` |
| Env (from Secret) | `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER=ctfd` |
| Service port | 3306 (ClusterIP) |

---

### Deployment: `redis`

| Attribute | Value |
|-----------|-------|
| Image | `redis:7-alpine` |
| Replicas | 1 |
| CPU limit | 0.1 |
| RAM limit | 256 Mi |
| Persistence | None |
| Auth | None (NetworkPolicy-protected) |
| Service port | 6379 (ClusterIP) |

---

### Deployment: `ctfd`

| Attribute | Value |
|-----------|-------|
| Image | `ctfd/ctfd:latest` |
| Replicas | 2 |
| CPU limit | 0.5 |
| RAM limit | 512 Mi |
| Init container | `busybox` — blocks until `nc -z mysql 3306` succeeds |

**Environment variables** (all via Secret or literal):

| Variable | Source | Value |
|----------|--------|-------|
| `DATABASE_URL` | Constructed | `mysql+pymysql://ctfd:<MYSQL_PASSWORD>@mysql/ctfd` |
| `REDIS_URL` | Literal | `redis://redis:6379` |
| `SECRET_KEY` | Secret `ctfd-secrets` | — |
| `SERVER_SENT_EVENTS` | Literal | `false` |
| `WORKERS` | Literal | `4` |
| `REVERSE_PROXY` | Literal | `true` (enables X-Forwarded-Proto trust) |
| `HTTP_RELATIVE_PATH` | Literal | `/` |
| `SESSION_COOKIE_SECURE` | Literal | `true` |
| `SESSION_COOKIE_HTTPONLY` | Literal | `true` |
| `MAIL_SERVER` | Operator-provided | SMTP hostname |
| `MAIL_PORT` | Operator-provided | e.g. `587` |
| `MAIL_USERNAME` | Operator-provided | SMTP username |
| `MAIL_PASSWORD` | Secret `ctfd-secrets` | — |
| `MAILFROM_ADDR` | Operator-provided | Sender address |

**Probes**:

| Probe | Path | Initial Delay | Period |
|-------|------|---------------|--------|
| Liveness | `GET /healthcheck` | 30 s | 10 s |
| Readiness | `GET /healthcheck` | 10 s | 5 s |

---

### Ingress: `ctfd-ingress`

| Attribute | Value |
|-----------|-------|
| Host | `ctfd.infodays.net` |
| Backend service | `ctfd-service:80` |
| TLS secret | `ctfd-tls-secret` (provisioned by Terraform cert-manager Certificate resource) |
| ClusterIssuer annotation | `cert-manager.io/cluster-issuer: letsencrypt-prod` |
| Ingress class | `nginx` |
| SSL redirect | `nginx.ingress.kubernetes.io/ssl-redirect: "true"` |
| Force SSL redirect | `nginx.ingress.kubernetes.io/force-ssl-redirect: "true"` |

---

## NetworkPolicy Additions (Phase 2)

These policies supplement the Phase 1 Terraform-managed policies. All are additive; NetworkPolicy rules are unioned.

| Policy Name | Selector | Direction | Destination | Port |
|-------------|----------|-----------|-------------|------|
| `allow-ctfd-egress-mysql` | `app: ctfd` | Egress | `app: mysql` in `ctfd` ns | TCP 3306 |
| `allow-ctfd-egress-redis` | `app: ctfd` | Egress | `app: redis` in `ctfd` ns | TCP 6379 |
| `allow-ctfd-egress-dns` | all pods | Egress | `kube-system` namespace (kube-dns) | UDP+TCP 53 |

**Why these are missing from Phase 1**: Phase 1 Terraform added ingress-side allows (MySQL INGRESS from CTFd, Redis INGRESS from CTFd) but did not add the corresponding CTFd EGRESS rules. DNS egress was also omitted. Without these, CTFd pods cannot resolve service names or establish outbound connections to MySQL/Redis.

---

## Data Flows

```
[Contestant Browser]
    │ HTTPS (443)
    ▼
[DigitalOcean Load Balancer]
    │ HTTP (80/443)
    ▼
[NGINX Ingress Controller — ingress-nginx ns]
    │ HTTP (80) — TLS terminated at ingress
    ▼
[ctfd-service — port 80 → 8000]
    │
[ctfd pods × 2]
    ├── TCP 3306 ──▶ [mysql service] ──▶ [mysql pod] ──▶ [PVC: mysql-data]
    └── TCP 6379 ──▶ [redis service] ──▶ [redis pod]

[Admin Machine]
    │ HTTPS (443) to ctfd.infodays.net/api/v1
    ├── setup-ctfd.sh ──▶ CTFd API (initial configuration)
    └── import-teams.py ──▶ CTFd Admin API (team creation)
```

## State Lifecycle

| State | Description |
|-------|-------------|
| Pre-deploy | Namespace exists (Phase 1); no application workloads |
| Secret created | `ctfd-secrets` applied (local file, not committed) |
| MySQL ready | StatefulSet running, PVC bound, database initialised |
| CTFd ready | Both replicas pass readiness probe at `/healthcheck` |
| Configured | `setup-ctfd.sh` has run; event settings applied via CTFd API |
| Teams imported | `import-teams.py` has run; all team accounts exist in CTFd |
| Event live | Teams login and compete; data written to MySQL PVC |
| Post-event | Data retained on PVC; teardown managed in Phase 6 |
