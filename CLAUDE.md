# infodays-ctf Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-04

## Active Technologies
- HCL (Terraform ≥1.5) for any Terraform additions; YAML (Kubernetes manifests); Bash (setup script); Python 3.11+ (import script) + `digitalocean` Terraform provider v2.x (already present); Kubernetes manifest files applied via `kubectl`; CTFd image `ctfd/ctfd:latest`; MySQL 8 image `mysql:8`; Redis 7 image `redis:7-alpine` (002-ctfd-platform-stack)
- MySQL 8 StatefulSet with 10 Gi PVC on `do-block-storage` StorageClass; Redis 7 StatefulSet with 1Gi PVC + AOF persistence (002-ctfd-platform-stack)
- Bash 5 (scripts), Dockerfile (BuildKit ≥ 1.4), Python 3.11 (web + misc examples), C11 (pwn binary) + Alpine Linux 3.19 (web, misc runtime), Ubuntu 22.04 (pwn runtime), socat 1.7 (pwn + misc), Flask 3.x (web example), Python 3.11-alpine (misc) (004-base-images-docr)
- N/A for service images; `challenge.zip` artifact written to host `./dist/` via BuildKit `--output` for static builder (004-base-images-docr)
- YAML (Kubernetes manifests), Bash 5 (test runner) + Kubernetes NetworkPolicy API, PSS admission controller (built-in), RBAC API (built-in), Cilium CNI (DOKS), `kubectl` (005-network-hardening-isolation)
- Bash 5 (backup script), k6 JavaScript ESM (load test) + k6 (load test runtime), kubectl + kubeconfig (backup + checklist), mysqldump (inside MySQL pod) (006-event-readiness-runbook)
- `backups/` (local host, SQL dumps), `tests/load/results/` (local host, JSON run summaries) (006-event-readiness-runbook)
- HCL (Terraform ≥1.5), YAML (Kubernetes manifests), Bash 5 (scripts), JavaScript ESM (k6 load tests) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x, ProxySQL 2.x, kubectl, k6 (007-100-team-scaling)
- MySQL 8 (StatefulSet, 10Gi PVC on `do-block-storage`), Redis 7 (StatefulSet, 1Gi PVC on `do-block-storage`, AOF persistence) (007-100-team-scaling)
- CSS3, Vanilla JavaScript (ES5/ES6), Python 3.11+ (Flask/CTFd plugin) + Bootstrap 5 (bundled with CTFd), Google Fonts CDN (Inter + JetBrains Mono), CTFd Blueprint static serving (008-ctfd-branding-ui-polish)
- N/A — no persistent data involved (008-ctfd-branding-ui-polish)

- Python 3.11+; `kubernetes` official Python client; `fastapi`; `uvicorn`; `httpx`; `pydantic` v2; `pytest` (003-challenge-controller-pod-lifecycle)
- Controller API: FastAPI (not Flask/Django) — single uvicorn worker, stateless, K8s annotations as lifecycle state (003-challenge-controller-pod-lifecycle)
- CTFd plugin: `CTFd/plugins/{name}/__init__.py` with `load(app: Flask)`, JS DOM injection from `assets/` Blueprint static folder (003-challenge-controller-pod-lifecycle)
- Challenge manifests: YAML files in `challenges/manifests/`, schema at `contracts/challenge-manifest-schema.yaml` (003-challenge-controller-pod-lifecycle)

- HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x, (001-cluster-network-foundation)

## Project Structure

```text
infra/
├── spaces-bootstrap/      # One-time Spaces bucket creation (local state)
├── terraform/             # Main IaC root module
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── cluster.tf
│   ├── registry.tf
│   ├── namespaces.tf
│   ├── network-policies.tf   # default-deny + allowlists for ctfd & challenges namespaces
│   ├── ingress.tf
│   ├── cert-manager.tf
│   └── dns.tf
└── tests/                 # bash acceptance tests (kubectl, curl, openssl)

controller/                # Challenge controller (FastAPI API + daemon + CLI scripts)
├── api.py                 # FastAPI: /activate, /deactivate, /status, /health
├── bulk_spawn.py          # Pre-spawn all (team × challenge) K8s resources at replicas=0
├── daemon.py              # Lifetime daemon — polls every 5 min, scales expired pods to 0
├── import_flags.py        # Pushes derived HMAC flags to CTFd admin API
├── flag.py                # derive_flag(team_id, challenge_id) → "infodays{...}"
├── manifest_loader.py     # Reads challenges/manifests/*.yaml
├── naming.py              # Deterministic resource naming conventions
├── k8s_client.py          # Auto-detect in-cluster or local kubeconfig
└── exceptions.py          # ChallengeNotFound, MaxInstancesExceeded, ControllerKeyInvalid

ctfd-plugin/               # CTFd plugin — Start/Stop UI + controller proxy
├── __init__.py            # Flask Blueprint: config.js endpoint + /controller-proxy/* routes
└── assets/
    └── plugin.js          # Bootstrap 5 modal events, status polling, activate/deactivate

challenges/
├── base-images/           # Dockerfiles for web, pwn, misc, static challenge types
│   ├── web/               # Flask app (port 8080), Alpine + Python 3.11
│   ├── pwn/               # socat + C binary (port 1337), Ubuntu 22.04
│   ├── misc/              # socat + Python puzzle (port 4444), Alpine
│   └── static/            # Build-only: produces challenge.zip via BuildKit --output
└── manifests/             # YAML challenge manifests (one per challenge)

k8s/
├── ctfd/                  # CTFd stack manifests (MySQL, Redis, CTFd, ingress, networkpolicy)
└── controller/            # Controller API + daemon deployments, RBAC

scripts/
├── deploy-challenge.sh    # One-command challenge deployment (6 automated steps)
├── push-challenge.sh      # Build → tag → push image to DOCR
├── setup-docr.sh          # Authenticate Docker to DOCR + DOKS integration
├── setup-ctfd.sh          # First-time CTFd setup + configuration
├── teardown-challenges.sh # Delete all managed-by=ctf-controller resources
└── import-teams.py        # Import teams + individual player accounts from CSV

specs/                     # Feature specs, plans, and design artifacts
```

## Commands

```bash
# Bootstrap state bucket (one-time) — creates infodays-ctf-tfstate in DO Spaces
terraform -chdir=infra/spaces-bootstrap apply \
  -var="do_token=$DIGITALOCEAN_TOKEN" \
  -var="do_spaces_access_key=$AWS_ACCESS_KEY_ID" \
  -var="do_spaces_secret_key=$AWS_SECRET_ACCESS_KEY" \
  -auto-approve

# Provision cluster (3-pass due to kubernetes_manifest chicken-and-egg)
terraform -chdir=infra/terraform init \
  -backend-config="access_key=$AWS_ACCESS_KEY_ID" \
  -backend-config="secret_key=$AWS_SECRET_ACCESS_KEY"

# Pass 1: cluster + registry
terraform -chdir=infra/terraform apply \
  -target=digitalocean_kubernetes_cluster.infodays \
  -target=digitalocean_container_registry.infodays \
  -auto-approve

# Pass 2: namespaces + helm releases (installs cert-manager CRDs)
doctl kubernetes cluster kubeconfig save infodays-ctf
terraform -chdir=infra/terraform apply \
  -target=kubernetes_namespace.cert_manager \
  -target=kubernetes_namespace.ctfd \
  -target=kubernetes_namespace.challenges \
  -target=kubernetes_namespace.monitoring \
  -target=kubernetes_namespace.ingress_nginx \
  -target=helm_release.ingress_nginx \
  -target=helm_release.cert_manager \
  -auto-approve

# Pass 3: everything else
terraform -chdir=infra/terraform apply -auto-approve

# Deploy CTFd stack (Phase 2)
kubectl apply -f k8s/ctfd/secrets.local.yaml   # ALWAYS apply secrets separately first
kubectl apply -f k8s/ctfd/services.yaml
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml
kubectl apply -f k8s/ctfd/mysql-replica-statefulset.yaml
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl apply -f k8s/ctfd/proxysql-deployment.yaml
kubectl apply -f k8s/ctfd/redis-deployment.yaml
kubectl apply -f k8s/ctfd/networkpolicy.yaml
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl apply -f k8s/ctfd/ingress.yaml
bash scripts/setup-mysql-replication.sh          # Configure GTID replication

# Configure CTFd and import teams + players
CTFD_URL=https://ctfd.infodays.net bash scripts/setup-ctfd.sh
# Or with auto-import during setup:
CTFD_URL=https://ctfd.infodays.net TEAMS_CSV=data/teams.csv bash scripts/setup-ctfd.sh
# Or import separately (CSV format: team_name,player_name,email,password):
python3 scripts/import-teams.py data/teams.csv \
  --ctfd-url https://ctfd.infodays.net \
  --admin-token "$CTFD_ADMIN_TOKEN"

# Deploy controller API + daemon
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml
kubectl apply -f k8s/controller/api-deployment.yaml
kubectl apply -f k8s/controller/daemon-deployment.yaml

# Apply network policies (challenges namespace)
kubectl apply -f k8s/network-policies/challenges-default-deny.yaml
kubectl apply -f k8s/network-policies/challenges-allow-ingress.yaml
kubectl apply -f k8s/network-policies/challenges-allow-nodeport.yaml
kubectl apply -f k8s/network-policies/challenges-allow-dns.yaml

# Deploy a challenge (one-command — creates CTFd entry, K8s resources, imports flags)
export CTFD_URL=https://ctfd.infodays.net
export CTFD_ADMIN_TOKEN=<token>
export CTF_MASTER_SECRET=<secret>
bash scripts/deploy-challenge.sh challenges/manifests/web-sqli.yaml

# Or deploy challenges manually (step by step):
# 1. Build & push image
bash scripts/push-challenge.sh base challenges/base-images/web web
# 2. Update ConfigMap + bulk spawn + import flags
kubectl create configmap challenge-manifests \
  --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/controller-api -n ctfd

# Run acceptance tests
bash infra/tests/validate-cluster.sh
bash infra/tests/validate-network-isolation.sh
bash infra/tests/validate-tls.sh
bash infra/tests/validate-ctfd.sh

# Teardown
terraform -chdir=infra/terraform destroy
```

## Code Style

HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers): Follow standard conventions

## Recent Changes
- 008-ctfd-branding-ui-polish: Added CSS3, Vanilla JavaScript (ES5/ES6), Python 3.11+ (Flask/CTFd plugin) + Bootstrap 5 (bundled with CTFd), Google Fonts CDN (Inter + JetBrains Mono), CTFd Blueprint static serving
- 007-100-team-scaling: Added HCL (Terraform ≥1.5), YAML (Kubernetes manifests), Bash 5 (scripts), JavaScript ESM (k6 load tests) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x, ProxySQL 2.x, kubectl, k6
- 006-load-testing: 200-VU soak tests (50 teams × 4 members, 45 min). CTFd scaled 2→5 replicas, workers 8→4, memory 512Mi→2Gi. MySQL memory 1Gi→2Gi (OOM fix), max-connections=500, innodb-buffer-pool-size=512MB. import_flags.py Content-Type fix. Challenge manifest names aligned to CTFd. tcp-services sequential port generation fix. Phase 7 planned for 100-team (400 VU) scaling with ProxySQL.

## Key Integration Details

### CTFd Plugin Architecture
- Script injection: Uses `CTFd.utils.plugins.register_script()` (not after_request HTML injection)
- Auth: `CTFd.utils.user.get_current_user()` for user info, `CTFd.utils.decorators.authed()` for auth checks
- CSRF: `window.init.csrfNonce` value, sent as `CSRF-Token` header
- Controller proxy: Browser → `/controller-proxy/*` (CTFd Flask) → `http://controller-api.ctfd.svc.cluster.local:80` (cluster-internal)
- Modal detection: Bootstrap 5 `shown.bs.modal` event on `#challenge-window`
- Challenge ID derivation: `name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")`

### Player Mode (individual accounts per team)
- CTFd `user_mode` is `"teams"` — each team has 4 individual player accounts (not 1 shared login)
- CSV format: `team_name,player_name,email,password` (one row per player, grouped by team_name)
- Template: `data/teams-template.csv`; real data: `data/teams.csv` (gitignored — contains credentials)
- Import: `python3 scripts/import-teams.py data/teams.csv` — creates teams + players, first player = captain
- All downstream systems (controller, flags, isolation, pod cap) use `team_id` — unaffected by player mode
- `get_current_team()` resolves any player → their team; `get_current_user()` identifies the individual
- Cheater detection: `cheaters` table includes `submitting_user_id` to identify the exact player
- ProxySQL workaround: plugin `CREATE TABLE IF NOT EXISTS` wrapped in try/except (DDL may route to replica)

### Network Policies (challenges namespace)
- `default-deny-all`: Blocks all ingress/egress by default
- `allow-ingress-to-challenges`: Allows ingress-nginx → challenge pods on ports 8080, 1337, 4444
- `allow-challenges-egress-dns`: Allows challenge pods → kube-system DNS (port 53)

### Network Policies (ctfd namespace)
- `allow-ctfd-egress-controller`: CTFd pods → controller-api on port 5000
- `allow-ctfd-to-controller-ingress`: controller-api accepts from CTFd on port 5000

### Challenge Ports
- Web challenges: port 8080 (not 80)
- Pwn challenges: port 1337
- Misc challenges: port 4444

### Dynamic Scoring
- All challenges use CTFd `type: dynamic` (not `standard`)
- Defaults: **initial=500**, **minimum=50**, **decay=25** solves
- Override per-manifest with `initial`, `minimum`, `decay` fields
- As more teams solve a challenge, its point value decreases from initial toward minimum
- `decay` = number of solves at which the value reaches the minimum

### Static File Challenges (`type: static`)
- For challenges with no running service — players download a file (e.g., forensics, crypto)
- Manifest: set `type: static` (no `image` or `port` needed)
- Flag: derived as `HMAC(CTF_MASTER_SECRET, "static:{challenge_id}")` — same for all teams
- Deploy script: builds zip with flag baked in, uploads to CTFd as file attachment, creates static flag
- `bulk_spawn.py` and `import_flags.py` skip `type: static` challenges (no K8s pods)
- Plugin UI: hides Start/Stop buttons for unmanaged challenges — CTFd's native download button handles it
- Custom content: place files in `challenges/static-content/{id}/` and they'll be included in the zip alongside `flag.txt`
- Example manifest:
  ```yaml
  id: misc-welcome
  name: "Welcome"
  category: misc
  type: static
  description: "Download the file and find the flag."
  ```

### Challenge Deployment Automation
```bash
# One-command deployment (recommended):
bash scripts/deploy-challenge.sh challenges/manifests/<id>.yaml

# Service challenges (type: http/tcp):
#   CTFd creation → ConfigMap update → controller restart → bulk_spawn → flag import

# Static challenges (type: static):
#   CTFd creation → build zip → upload file → create static flag (no K8s resources)
```

### CTFd Token Auth Quirk
- CTFd requires `Content-Type: application/json` header on ALL requests using API token auth, including GETs
- Without it, CTFd's `tokens()` middleware skips auth processing and returns 302 redirect to login
- All API calls in import_flags.py, scripts, and k6 tests must include this header

### Resource Sizing (validated under 200-VU load, 0.00% error rate)
- CTFd: 5 replicas, 4 gevent workers each, 2Gi memory limit, 1000m CPU request, CACHE_TYPE=redis
- MySQL primary: 1 replica, 4Gi memory limit, max-connections=500, GTID replication enabled
- MySQL read replica: 1 replica, 2Gi memory limit, super-read-only enabled via SQL after replication starts (NOT as container arg — blocks Docker init)
- ProxySQL: 2 replicas, read/write splitting (hostgroup 0=writer, 1=reader), max_connections=200 per backend
- Controller API: **8 replicas, 8 uvicorn workers each**, 1Gi memory limit, 250m CPU request (IO-bound), 5s status cache TTL
- Redis: **StatefulSet** with 1Gi PVC on do-block-storage, AOF persistence (appendonly yes, appendfsync everysec)
- Node pool: autoscaling 3–8 × s-4vcpu-8gb

### MySQL Replication
- GTID-based replication: primary (mysql-0) → replica (mysql-replica-0)
- Setup script: `bash scripts/setup-mysql-replication.sh` (idempotent)
- ProxySQL `mysql_replication_hostgroups` auto-shuns replica if it falls behind
- SELECT queries → replica (hostgroup 1), writes → primary (hostgroup 0)
- SELECT ... FOR UPDATE → primary (write-intent reads must not hit replica)

### TCP Port Map Generation
- tcp-services ConfigMap entries MUST be generated sequentially (not in parallel threads)
- Race condition validated: parallel bulk_spawn produced 43/100 entries instead of 100
- Fix: single-threaded Python generator → single kubectl patch

### CiliumNetworkPolicy (DOKS-specific)
- Standard Kubernetes NetworkPolicy cannot target kube-apiserver on DOKS (Cilium CNI)
- Controller needs `CiliumNetworkPolicy` with `toEntities: [kube-apiserver]` for K8s API access
- ClusterRole + ClusterRoleBinding needed for node listing (NodePort discovery)

### HTTP Challenge Isolation (nginx auth_request)
- All HTTP challenge Ingresses carry two nginx annotations:
  - `auth-url: http://ctfd-service.ctfd.svc.cluster.local/team-verify?host=$host` — server-side auth sub-request
  - `auth-signin: https://ctfd.infodays.net/login` — redirect destination on 401
- CTFd plugin exposes `/team-verify`: parses `team-{id}-{challenge}` from `?host=`, returns 200/401/403
- **SESSION_COOKIE_DOMAIN must be `.infodays.net`** (not `ctfd.infodays.net`) so the session cookie is sent to `*.challenges.infodays.net`. Set in `load(app)` as `app.config["SESSION_COOKIE_DOMAIN"] = ".infodays.net"` — Flask ignores the env var, it must be set in app config.
- After changing SESSION_COOKIE_DOMAIN, run `kubectl exec -n ctfd redis-0 -- redis-cli FLUSHDB` to clear old-domain cookies that cause login loops.
- **TCP challenges (nc)** are NOT isolated by URL — NodePort bypasses nginx. Isolation is cryptographic only (HMAC flags unique per team).

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
