# Quickstart: CTFd Platform Stack

**Branch**: `002-ctfd-platform-stack` | **Date**: 2026-03-24

## Prerequisites

- Phase 1 complete: cluster running, `ctfd` namespace exists, ingress controller and cert-manager deployed, DNS pointing `ctfd.infodays.net` at the load balancer.
- `kubectl` configured with cluster credentials (`doctl kubernetes cluster kubeconfig save <cluster-name>`).
- Python 3.11+ available locally for running import script.

## Step 1 — Prepare Secrets

Copy the secret template and fill in real values:

```bash
cp k8s/ctfd/secrets.yaml k8s/ctfd/secrets.local.yaml
# Edit secrets.local.yaml — replace all CHANGE_ME placeholders with real values
# This file must NOT be committed to git
```

Required values:
- `MYSQL_ROOT_PASSWORD` — strong random password
- `MYSQL_PASSWORD` — strong random password (different from root)
- `SECRET_KEY` — random 32+ byte string (e.g., `openssl rand -hex 32`)
- `MAIL_PASSWORD` — SMTP password (leave empty if mail not needed)
- `CTF_MASTER_SECRET` — random 32+ byte string (reserved for Phase 3; set now)

## Step 2 — Apply Manifests

> **⚠️ CRITICAL**: Apply secrets FIRST and separately. Do NOT use `kubectl apply -f k8s/ctfd/` — it will also apply `secrets.yaml` (the template with `CHANGE_ME` values), overwriting your real secrets.

```bash
# Apply secrets first (real values)
kubectl apply -f k8s/ctfd/secrets.local.yaml

# Apply remaining manifests individually
kubectl apply -f k8s/ctfd/services.yaml
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml
kubectl apply -f k8s/ctfd/redis-deployment.yaml
kubectl apply -f k8s/ctfd/networkpolicy.yaml
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl apply -f k8s/ctfd/ingress.yaml
```

## Step 3 — Wait for Readiness

```bash
# Watch rollout
kubectl -n ctfd rollout status statefulset/mysql
kubectl -n ctfd rollout status deployment/redis
kubectl -n ctfd rollout status deployment/ctfd

# Verify all pods running
kubectl -n ctfd get pods
```

Expected output: 1 mysql pod, 1 redis pod, 2 ctfd pods — all `Running`.

## Step 4 — Configure CTFd

```bash
export CTFD_URL="https://ctfd.infodays.net"
export CTFD_ADMIN_TOKEN="<your-admin-token>"
bash scripts/setup-ctfd.sh
```

The script polls `/healthcheck` until CTFd is ready, then applies event configuration.

## Step 5 — Import Teams

```bash
# Prepare team data
cp data/teams-template.csv data/teams.csv
# Edit data/teams.csv with real team names, emails, passwords
# (data/teams.csv must not be committed)

python scripts/import-teams.py \
  --ctfd-url https://ctfd.infodays.net \
  --admin-token "$CTFD_ADMIN_TOKEN" \
  data/teams.csv
```

## Step 6 — Run Acceptance Tests

```bash
bash infra/tests/validate-ctfd.sh
```

All tests must pass before the event goes live.

## Teardown

Teardown is out of scope for Phase 2 — managed in Phase 6 runbook.

For emergency removal of application workloads only (preserves cluster infrastructure):

```bash
kubectl delete -f k8s/ctfd/
# Note: this does NOT delete the PVC — MySQL data is retained
# To also delete PVC: kubectl -n ctfd delete pvc mysql-data
```

## Troubleshooting

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| CTFd pods crash-looping | MySQL not ready yet | `kubectl -n ctfd logs <ctfd-pod> -c init-wait-for-mysql` |
| TLS certificate pending | DNS not propagated | `kubectl -n ctfd describe certificate ctfd-tls-secret` |
| Cannot reach ctfd.infodays.net | Load balancer IP changed | `kubectl -n ingress-nginx get svc` — check external IP |
| setup-ctfd.sh times out | CTFd pods not healthy | `kubectl -n ctfd get pods` — check readiness |
| import-teams.py auth error | Admin token wrong/expired | Regenerate token in CTFd admin panel |
