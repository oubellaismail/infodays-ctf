# Quickstart: Challenge Controller & Pod Lifecycle

**Feature**: `003-challenge-controller-pod-lifecycle`
**Prerequisites**: Phase 1 (cluster running) + Phase 2 (CTFd deployed)

---

## Local Development Setup

```bash
# 1. Create k3d cluster (constitution mandates k3d, not minikube/kind)
k3d cluster create infodays-dev --agents 2 --port "80:80@loadbalancer" --port "443:443@loadbalancer"

# 2. Install NGINX Ingress (same Helm chart as DOKS)
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace

# 3. Create required namespaces
kubectl create namespace challenges
kubectl create namespace ctfd

# 4. Set required secrets
kubectl create secret generic ctfd-secrets -n ctfd \
  --from-literal=CTF_MASTER_SECRET="local-dev-secret-change-me"
kubectl create secret generic controller-key -n ctfd \
  --from-literal=CONTROLLER_KEY="local-dev-key-change-me"

# 5. Install Python dependencies
cd controller
pip install -r requirements.txt
```

---

## Pre-Event Workflow

### Option A — One-command deployment (recommended)

```bash
# deploy-challenge.sh automates all steps: CTFd entry, ConfigMap, controller restart,
# bulk_spawn, and flag import. Run once per challenge manifest.

export CTFD_URL=https://ctfd.infodays.net
export CTFD_ADMIN_TOKEN=$CTFD_ADMIN_TOKEN
export CTF_MASTER_SECRET=$CTF_MASTER_SECRET

bash scripts/deploy-challenge.sh challenges/manifests/web-sqli.yaml
bash scripts/deploy-challenge.sh challenges/manifests/pwn-bof.yaml
bash scripts/deploy-challenge.sh challenges/manifests/misc-riddle.yaml
```

### Option B — Manual step-by-step

### Step 1 — Deploy controller API and daemon

```bash
# Apply secrets first (always separate from other manifests)
kubectl apply -f k8s/controller/secrets.local.yaml   # contains CONTROLLER_KEY

# Deploy controller FastAPI (mounts challenge-manifests ConfigMap)
kubectl apply -f k8s/controller/api-deployment.yaml

# Deploy lifetime daemon
kubectl apply -f k8s/controller/daemon-deployment.yaml

# Verify
kubectl get pods -n ctfd
# NAME                          READY   STATUS    RESTARTS   AGE
# controller-api-xxx            1/1     Running   0          30s
# controller-daemon-xxx         1/1     Running   0          30s
```

### Step 2 — Verify challenge manifests

```bash
# Manifests live in challenges/manifests/*.yaml
# Each file must conform to contracts/challenge-manifest-schema.yaml
# IMPORTANT: web challenges use port 8080, pwn uses 1337, misc uses 4444
ls challenges/manifests/
```

### Step 3 — Update challenge-manifests ConfigMap

```bash
# The controller API loads manifests from a ConfigMap mounted at /app/challenges/manifests
# Update it whenever manifests change, then restart the controller
kubectl create configmap challenge-manifests \
  --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/controller-api -n ctfd
```

### Step 4 — Bulk pre-spawn all resources

```bash
# Reads teams from CTFd admin API + manifests from challenges/manifests/
# Creates Deployments (replicas=0), Secrets, Services, Ingresses/TCP entries
# Includes PodSecurity-compliant security context (restricted:latest)
# Idempotent — safe to re-run

# Run inside the controller pod (has K8s credentials + manifests):
CONTROLLER_POD=$(kubectl get pods -n ctfd -l app=controller-api \
  --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n ctfd $CONTROLLER_POD -- \
  env CTFD_ADMIN_TOKEN=$CTFD_ADMIN_TOKEN \
  python3 /app/bulk_spawn.py --ctfd-url https://ctfd.infodays.net --token $CTFD_ADMIN_TOKEN
```

### Step 5 — Import derived flags into CTFd

```bash
# Derives HMAC-SHA256 flag for every (team, service-challenge) pair
# Posts each flag to CTFd admin API — idempotent

kubectl exec -n ctfd $CONTROLLER_POD -- \
  env CTFD_ADMIN_TOKEN=$CTFD_ADMIN_TOKEN \
  python3 /app/import_flags.py --ctfd-url https://ctfd.infodays.net
```

---

## Testing Key Flows

### Verify flag derivation

```bash
python controller/flag.py --team 3 --challenge web-sqli
# infodays{a3f1c2d4e5b6...}  (32 hex chars)
```

### Test activation / deactivation manually

```bash
# Activate (replace URL with controller service address)
curl -X POST http://localhost:5000/activate \
  -H "Content-Type: application/json" \
  -H "X-Controller-Key: local-dev-key-change-me" \
  -d '{"team_id": "999", "challenge_id": "test-web-sqli"}'
# {"status": "starting", "url": "http://challenges.infodays.net:32569"}

# Check status
curl http://localhost:5000/status/999 \
  -H "X-Controller-Key: local-dev-key-change-me"

# Deactivate
curl -X POST http://localhost:5000/deactivate \
  -H "Content-Type: application/json" \
  -H "X-Controller-Key: local-dev-key-change-me" \
  -d '{"team_id": "999", "challenge_id": "test-web-sqli"}'
# {"status": "suspended"}
```

### Test 4-pod cap

```bash
# Activate 4 challenges for test team
for c in test-web-1 test-web-2 test-pwn-1 test-misc-1; do
  curl -s -X POST http://localhost:5000/activate \
    -H "Content-Type: application/json" \
    -H "X-Controller-Key: local-dev-key-change-me" \
    -d "{\"team_id\": \"999\", \"challenge_id\": \"$c\"}"
done

# 5th activation must return 429
curl -s -X POST http://localhost:5000/activate \
  -H "Content-Type: application/json" \
  -H "X-Controller-Key: local-dev-key-change-me" \
  -d '{"team_id": "999", "challenge_id": "test-web-3"}' | jq .
# {"error": "Max 4 active instances reached. Stop one to continue."}
```

### Test daemon lifetime expiry

```bash
# Manually backdate ctf/activated-at to 61 minutes ago
kubectl annotate deployment team-999-test-web-sqli \
  -n challenges \
  ctf/activated-at="$(date -u -d '61 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --overwrite

# Run one daemon iteration
python controller/daemon.py --once    # (requires --once flag in implementation)

# Verify deployment scaled to 0
kubectl get deploy team-999-test-web-sqli -n challenges -o jsonpath='{.spec.replicas}'
# 0
```

### Run unit tests

```bash
cd controller
pytest tests/unit/ -v
```

---

## End-of-Event Teardown

```bash
# Deletes ALL resources labeled managed-by=ctf-controller in challenges namespace
# Requires confirmation prompt before executing
bash scripts/teardown-challenges.sh

# Expected output:
# WARNING: This will delete all challenge pods, secrets, services, and ingresses.
# Type 'yes' to confirm: yes
# Deleting Deployments... done
# Deleting Secrets... done
# Deleting Services... done
# Deleting Ingresses... done
# Teardown complete.
```

---

## Naming Quick Reference

| Resource | Pattern | Example |
|----------|---------|---------|
| Deployment | `team-{team_id}-{challenge_id}` | `team-3-web-sqli` |
| Secret | `team-{team_id}-{challenge_id}-secret` | `team-3-web-sqli-secret` |
| Service | `team-{team_id}-{challenge_id}-svc` | `team-3-web-sqli-svc` |
| Ingress | `team-{team_id}-{challenge_id}-ingress` | `team-3-web-sqli-ingress` |
| Test team_id | `999` | — |
| Test challenge prefix | `test-` | `test-web-sqli` |

---

## Environment Variables Required

| Variable | Where Set | Description |
|----------|-----------|-------------|
| `CTF_MASTER_SECRET` | K8s Secret `ctfd-secrets` | HMAC key for flag derivation |
| `CONTROLLER_KEY` | K8s Secret `controller-key` | Shared secret for API auth |
| `CTFD_URL` | Deployment env or shell | CTFd base URL for admin API calls |
| `CTFD_ADMIN_TOKEN` | Shell / CI secret | CTFd admin API token |

## Network Policies Required

The `challenges` namespace uses default-deny. These policies must be in place:

| Policy | Purpose |
|--------|---------|
| `default-deny-all` | Blocks all ingress/egress by default (Terraform-managed) |
| `allow-ingress-to-challenges` | ingress-nginx → challenge pods on ports 8080, 1337, 4444 |
| `allow-challenges-egress-dns` | challenge pods → kube-system DNS (port 53 UDP/TCP) |

The `ctfd` namespace also requires policies for controller communication:

| Policy | Purpose |
|--------|---------|
| `allow-ctfd-egress-controller` | CTFd pods → controller-api on port 5000 |
| `allow-ctfd-to-controller-ingress` | controller-api accepts from CTFd pods on port 5000 |

## CTFd Plugin Architecture

The CTFd plugin (`ctfd-plugin/`) provides the Start/Stop UI in challenge modals:

- **Script injection**: `register_script()` from `CTFd.utils.plugins` — loads `config.js` (per-user config) and `plugin.js` (UI logic)
- **Controller proxy**: Browser calls `/controller-proxy/*` on CTFd, which proxies to `http://controller-api.ctfd.svc.cluster.local` (never exposed to browser)
- **Auth**: Uses `CTFd.utils.user.get_current_user()` and `CTFd.utils.decorators.authed()`
- **CSRF**: Reads `window.init.csrfNonce`, sends as `CSRF-Token` header
- **Modal detection**: Listens for Bootstrap 5 `shown.bs.modal` event on `#challenge-window`
- **Challenge ID mapping**: Derives slug from CTFd challenge name: `name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")`
