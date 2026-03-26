# infodays-ctf Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-26

## Active Technologies
- HCL (Terraform ≥1.5) for any Terraform additions; YAML (Kubernetes manifests); Bash (setup script); Python 3.11+ (import script) + `digitalocean` Terraform provider v2.x (already present); Kubernetes manifest files applied via `kubectl`; CTFd image `ctfd/ctfd:latest`; MySQL 8 image `mysql:8`; Redis 7 image `redis:7-alpine` (002-ctfd-platform-stack)
- MySQL 8 StatefulSet with 10 Gi PVC on `do-block-storage` StorageClass; Redis ephemeral (no PVC) (002-ctfd-platform-stack)
- Bash 5 (scripts), Dockerfile (BuildKit ≥ 1.4), Python 3.11 (web + misc examples), C11 (pwn binary) + Alpine Linux 3.19 (web, misc runtime), Ubuntu 22.04 (pwn runtime), socat 1.7 (pwn + misc), Flask 3.x (web example), Python 3.11-alpine (misc) (004-base-images-docr)
- N/A for service images; `challenge.zip` artifact written to host `./dist/` via BuildKit `--output` for static builder (004-base-images-docr)
- YAML (Kubernetes manifests), Bash 5 (test runner) + Kubernetes NetworkPolicy API, PSS admission controller (built-in), RBAC API (built-in), Cilium CNI (DOKS), `kubectl` (005-network-hardening-isolation)

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
└── import-teams.py        # Import teams from CSV into CTFd

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
kubectl apply -f k8s/ctfd/redis-deployment.yaml
kubectl apply -f k8s/ctfd/networkpolicy.yaml
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl apply -f k8s/ctfd/ingress.yaml

# Configure CTFd and import teams
CTFD_URL=https://ctfd.infodays.net bash scripts/setup-ctfd.sh
python3 scripts/import-teams.py data/teams.csv \
  --ctfd-url https://ctfd.infodays.net \
  --admin-token "$CTFD_ADMIN_TOKEN"

# Deploy controller API + daemon
kubectl apply -f k8s/controller/rbac.yaml
kubectl apply -f k8s/controller/api-deployment.yaml
kubectl apply -f k8s/controller/daemon-deployment.yaml

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
- 005-network-hardening-isolation: Enforced network isolation — standalone NetworkPolicy YAMLs for challenges+ctfd namespaces, scoped `allow-ctfd-egress-internet` to controller-api pods only, complete RBAC for ctf-controller (all verbs) + new ctf-daemon SA with least-privilege Role, PSS namespace-labels.yaml, 4-pod isolation test suite + run-isolation-tests.sh (4/4 tests pass on cluster)
- 005-integration-fixes: Fixed end-to-end challenge flow — CTFd plugin rewritten (register_script + proxy routes), network policies for challenges namespace, PodSecurity compliance in bulk_spawn, port fixes, deploy-challenge.sh automation script
- 004-base-images-docr: Added Bash 5 (scripts), Dockerfile (BuildKit ≥ 1.4), Python 3.11 (web + misc examples), C11 (pwn binary) + Alpine Linux 3.19 (web, misc runtime), Ubuntu 22.04 (pwn runtime), socat 1.7 (pwn + misc), Flask 3.x (web example), Python 3.11-alpine (misc)

## Key Integration Details

### CTFd Plugin Architecture
- Script injection: Uses `CTFd.utils.plugins.register_script()` (not after_request HTML injection)
- Auth: `CTFd.utils.user.get_current_user()` for user info, `CTFd.utils.decorators.authed()` for auth checks
- CSRF: `window.init.csrfNonce` value, sent as `CSRF-Token` header
- Controller proxy: Browser → `/controller-proxy/*` (CTFd Flask) → `http://controller-api.ctfd.svc.cluster.local:80` (cluster-internal)
- Modal detection: Bootstrap 5 `shown.bs.modal` event on `#challenge-window`
- Challenge ID derivation: `name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")`

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

### Challenge Deployment Automation
```bash
# One-command deployment (recommended):
bash scripts/deploy-challenge.sh challenges/manifests/<id>.yaml
# Automates: CTFd creation → ConfigMap update → controller restart → bulk_spawn → flag import
```

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
