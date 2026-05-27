# Cluster & Networking Foundation — Terraform Configuration

This module provisions the complete InfoDays CTF infrastructure on DigitalOcean: DOKS cluster, DOCR registry, namespaces, NGINX ingress, cert-manager, and all networking.

## Prerequisites Checklist

Before running Terraform:

- [ ] **DNS delegated**: `infodays.net` is on Cloudflare nameservers, with NS records in Cloudflare delegating `ctfd.infodays.net` and `challenges.infodays.net` to DigitalOcean (`ns1/ns2/ns3.digitalocean.com`). The root domain must NOT be moved to DigitalOcean (it hosts a separate Netlify site). See [DNS Architecture](#dns-architecture) below.
- [ ] **Bootstrap done**: Spaces bucket `infodays-ctf-tfstate` exists (run `infra/spaces-bootstrap/` first)
- [ ] **Terraform state backend**: `infodays-ctf-tfstate` bucket is accessible with your Spaces credentials
- [ ] **DigitalOcean API tokens**: You have both `do_token` (cluster/registry/DNS) and `do_dns_token` (DNS-01 ACME)
- [ ] **Terraform ≥1.5**: Installed and in your PATH
- [ ] **kubectl**: Installed locally for post-apply validation

## Quick Start

### 1. Create `terraform.tfvars`

Copy from the example:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and fill in:

```hcl
do_token           = "dop_v1_..."       # Your DO API token
do_dns_token       = "dop_v1_..."       # DNS token (can be same as do_token)
letsencrypt_email  = "ops@infodays.net" # Email for Let's Encrypt
```

**⚠️ CRITICAL**: This file is gitignored — never commit it.

### 2. Export Spaces backend credentials

The S3-compatible backend cannot read Terraform variables. Supply Spaces credentials
as environment variables **before** running `terraform init`:

```bash
export AWS_ACCESS_KEY_ID="<your-spaces-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-spaces-secret-key>"
```

These are the same Spaces access key and secret key used for the bootstrap bucket.

### 3. Initialize Terraform

```bash
terraform init
```

Terraform will connect to the `infodays-ctf-tfstate` Spaces bucket and download providers.

### 5. Plan and Review

```bash
terraform plan
```

Review the output. You should see:
- 1 DOCR registry
- 1 DOKS cluster (4 general worker nodes)
- 1 dedicated MySQL node pool (`mysql-pool`, 1 × `s-4vcpu-8gb`)
- 3 namespaces
- 1 NGINX Ingress Controller
- 2 DNS A-records
- cert-manager and ClusterIssuer
- All supporting K8s resources

### 6. Apply

Due to a bootstrap ordering constraint (`kubernetes_manifest` resources require the cluster API to be reachable during plan), apply must be run in **two passes**:

**Pass 1** — cluster only (registry must be imported if it already exists):
```bash
terraform apply \
  -target=digitalocean_kubernetes_cluster.infodays \
  -target=digitalocean_container_registry.infodays \
  -auto-approve
```

**Pass 2** — save kubeconfig, then install namespaces and Helm releases (cert-manager CRDs must exist before Pass 3):
```bash
doctl kubernetes cluster kubeconfig save infodays-ctf

terraform apply \
  -target=kubernetes_namespace.cert_manager \
  -target=kubernetes_namespace.ctfd \
  -target=kubernetes_namespace.challenges \
  -target=kubernetes_namespace.monitoring \
  -target=kubernetes_namespace.ingress_nginx \
  -target=helm_release.ingress_nginx \
  -target=helm_release.cert_manager \
  -auto-approve
```

**Pass 3** — everything else (ClusterIssuer, certificates, DNS, network policies):
```bash
terraform apply -auto-approve
```

> **Note**: If the container registry already exists in DigitalOcean (e.g. after a manual dashboard delete that left the name reserved), import it before Pass 1:
> ```bash
> terraform import digitalocean_container_registry.infodays infodays-registry
> ```

Total time: **15–20 minutes**.

## Validation

After apply completes, run the validation suite:

```bash
# Export kubeconfig
terraform output -raw kubeconfig | base64 -d > ~/.kube/infodays-ctf.yaml
export KUBECONFIG=~/.kube/infodays-ctf.yaml

# Run all validation tests
bash ../tests/validate-cluster.sh
bash ../tests/validate-tls.sh
bash ../tests/validate-network-isolation.sh
bash ../tests/validate-psa.sh
```

All tests must pass (exit code 0).

## Outputs

After `terraform apply`, retrieve outputs:

```bash
# Cluster endpoint
terraform output -raw cluster_endpoint

# Ingress IP
terraform output -raw ingress_lb_ip

# DOCR endpoint
terraform output -raw registry_endpoint

# Kubeconfig (sensitive)
terraform output -raw kubeconfig | base64 -d > kubeconfig.yaml
```

## File Structure

```text
.
├── providers.tf           # Provider config + backend
├── variables.tf           # All input variables
├── outputs.tf             # Output values
├── cluster.tf             # DOKS cluster + node pool
├── mysql-node-pool.tf     # Dedicated MySQL node pool
├── registry.tf            # DOCR + pull-secret configuration
├── namespaces.tf          # K8s namespaces + PSA labels
├── network-policies.tf    # Default-deny + allowlist policies
├── ingress.tf             # NGINX Ingress Controller
├── cert-manager.tf        # cert-manager + certificates
├── dns.tf                 # A-records for platform domains
├── terraform.tfvars.example
└── README.md (this file)
```

## Managing State

The Terraform state is stored remotely in the `infodays-ctf-tfstate` Spaces bucket. This allows sharing the state with team members.

```bash
# View state summary
terraform state list

# Refresh state from actual resources (if manual changes were made)
terraform refresh

# Show a specific resource
terraform state show digitalocean_kubernetes_cluster.infodays
```

## Updating Configuration

If you need to change cluster settings (e.g., node count):

1. Edit the variable in `terraform.tfvars`
2. Run `terraform plan` to see the changes
3. Run `terraform apply` to apply them

**Note**: Some changes (like node size or cluster version) may be destructive. Always review the plan first.

## DNS Architecture

The root domain `infodays.net` is on **Cloudflare** nameservers (not DigitalOcean) because it hosts a separate Netlify site. Only the CTF subdomains are delegated to DigitalOcean:

```
infodays.net          → Cloudflare (authoritative)
  ctfd.infodays.net       → NS delegation → DigitalOcean
  challenges.infodays.net → NS delegation → DigitalOcean
```

**Cloudflare NS records required** (DNS only, grey cloud — no proxy):

| Type | Name | Value |
|------|------|-------|
| NS | `ctfd` | `ns1.digitalocean.com` |
| NS | `ctfd` | `ns2.digitalocean.com` |
| NS | `ctfd` | `ns3.digitalocean.com` |
| NS | `challenges` | `ns1.digitalocean.com` |
| NS | `challenges` | `ns2.digitalocean.com` |
| NS | `challenges` | `ns3.digitalocean.com` |

**Why this matters for TLS**: cert-manager uses DigitalOcean's API to write ACME DNS-01 challenge TXT records. Let's Encrypt follows the NS delegation from Cloudflare to DigitalOcean and finds the TXT records there. Without this delegation, certificates will stay `Ready: False` indefinitely.

**Important**: `terraform apply` creates the DigitalOcean zones (`ctfd.infodays.net`, `challenges.infodays.net`). The NS records in Cloudflare can be added before or after apply — both sides must exist for resolution to complete.

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `init` fails with backend error | Spaces bucket doesn't exist or credentials wrong | Run bootstrap and verify credentials |
| `apply` fails on DNS record | LB IP not yet assigned | Wait 2–3 minutes and re-run apply |
| Certificate stays Pending | Subdomain NS delegation not in place | Verify Cloudflare has NS records for `ctfd.infodays.net` and `challenges.infodays.net` pointing to DigitalOcean. Then run `terraform apply` — DigitalOcean zones must exist for delegation to resolve. |
| Pod admission rejected | PSA standard violation | Pod must run as uid=1000 (not root) |
| Image pull fails | DOCR pull-secret not applied | Check ServiceAccount in namespace |

## Cleanup / Teardown

To destroy all infrastructure:

```bash
terraform destroy
```

**⚠️ WARNING**: This deletes the cluster, registry, and all resources. Verify you're destroying the correct workspace/environment.

After destruction, the Spaces state bucket remains (managed separately). Delete it manually if desired.

## References

- **Specification**: `../../specs/001-cluster-network-foundation/spec.md`
- **Implementation Plan**: `../../specs/001-cluster-network-foundation/plan.md`
- **Design Documents**: `../../specs/001-cluster-network-foundation/data-model.md`, `contracts/`, `research.md`
- **Operator Quickstart**: `../../specs/001-cluster-network-foundation/quickstart.md`
