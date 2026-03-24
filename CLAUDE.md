# infodays-ctf Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-24

## Active Technologies
- HCL (Terraform ≥1.5) for any Terraform additions; YAML (Kubernetes manifests); Bash (setup script); Python 3.11+ (import script) + `digitalocean` Terraform provider v2.x (already present); Kubernetes manifest files applied via `kubectl`; CTFd image `ctfd/ctfd:latest`; MySQL 8 image `mysql:8`; Redis 7 image `redis:7-alpine` (002-ctfd-platform-stack)
- MySQL 8 StatefulSet with 10 Gi PVC on `do-block-storage` StorageClass; Redis ephemeral (no PVC) (002-ctfd-platform-stack)

- HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x, (001-cluster-network-foundation)

## Project Structure

```text
infra/
├── spaces-bootstrap/      # One-time Spaces bucket creation (local state)
└── terraform/             # Main IaC root module
    ├── providers.tf
    ├── variables.tf
    ├── outputs.tf
    ├── cluster.tf
    ├── registry.tf
    ├── namespaces.tf
    ├── network-policies.tf
    ├── ingress.tf
    ├── cert-manager.tf
    └── dns.tf
infra/tests/               # bash acceptance tests (kubectl, curl, openssl)
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
- 002-ctfd-platform-stack: Added HCL (Terraform ≥1.5) for any Terraform additions; YAML (Kubernetes manifests); Bash (setup script); Python 3.11+ (import script) + `digitalocean` Terraform provider v2.x (already present); Kubernetes manifest files applied via `kubectl`; CTFd image `ctfd/ctfd:latest`; MySQL 8 image `mysql:8`; Redis 7 image `redis:7-alpine`

- 001-cluster-network-foundation: Added HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x,

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
