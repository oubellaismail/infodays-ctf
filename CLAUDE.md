# infodays-ctf Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-21

## Active Technologies

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
# Bootstrap state bucket (one-time)
terraform -chdir=infra/spaces-bootstrap init && terraform -chdir=infra/spaces-bootstrap apply

# Provision cluster
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform plan
terraform -chdir=infra/terraform apply

# Run acceptance tests
bash infra/tests/validate-cluster.sh
bash infra/tests/validate-network-isolation.sh
bash infra/tests/validate-tls.sh

# Teardown
terraform -chdir=infra/terraform destroy
```

## Code Style

HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers): Follow standard conventions

## Recent Changes

- 001-cluster-network-foundation: Added HCL (Terraform ≥1.5); YAML (Kubernetes manifests via TF providers) + Terraform `digitalocean` provider v2.x, `helm` provider v2.x,

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
