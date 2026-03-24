# Quickstart: Cluster & Networking Foundation

**Feature**: 001-cluster-network-foundation
**Date**: 2026-03-21
**Audience**: CTF operator provisioning the cluster for the first time

---

## Prerequisites

Before running any Terraform commands:

1. **DigitalOcean API token** with read/write permissions for clusters,
   registries, DNS, and Spaces. Store it securely (password manager or vault).

2. **DNS delegation**: `infodays.net` is on **Cloudflare** nameservers (the root
   domain hosts a separate Netlify site and must NOT be moved to DigitalOcean).
   In Cloudflare, NS records MUST delegate the two CTF subdomains to DigitalOcean:

   | Type | Name | Value |
   |------|------|-------|
   | NS | `ctfd` | `ns1.digitalocean.com` |
   | NS | `ctfd` | `ns2.digitalocean.com` |
   | NS | `ctfd` | `ns3.digitalocean.com` |
   | NS | `challenges` | `ns1.digitalocean.com` |
   | NS | `challenges` | `ns2.digitalocean.com` |
   | NS | `challenges` | `ns3.digitalocean.com` |

   Set proxy status to **DNS only (grey cloud)** — do NOT proxy through Cloudflare.

   Verify after adding:
   ```bash
   dig NS ctfd.infodays.net +short
   # Expected: ns1.digitalocean.com. ns2.digitalocean.com. ns3.digitalocean.com.
   ```

   **Important**: `terraform apply` creates the DigitalOcean zones. The NS records
   in Cloudflare can be added before or after apply — both must exist for
   certificate issuance to complete.

3. **Terraform ≥1.5** installed locally.

4. **kubectl** installed locally.

---

## Step 1: Bootstrap the Terraform State Bucket (one-time)

This step creates the DigitalOcean Spaces bucket that stores Terraform state.
It must run exactly once before initialising the main module.

```bash
cd infra/spaces-bootstrap/

# Provide credentials
export TF_VAR_do_token="<your-do-token>"
export TF_VAR_do_spaces_access_key="<your-spaces-access-key>"
export TF_VAR_do_spaces_secret_key="<your-spaces-secret-key>"

terraform init
terraform apply
```

Confirm the bucket `infodays-tfstate` is created in `fra1`.

---

## Step 2: Configure Variables

```bash
cd infra/terraform/

cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — fill in all required values
# This file is gitignored — never commit it
```

Minimum `terraform.tfvars` content:
```hcl
do_token          = "dop_v1_..."
do_dns_token      = "dop_v1_..."   # MAY be same as do_token
letsencrypt_email = "ops@infodays.net"
```

**Spaces credentials are NOT Terraform variables** — the S3 backend reads them
from environment variables. Export these before running `terraform init`:
```bash
export AWS_ACCESS_KEY_ID="<your-spaces-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-spaces-secret-key>"
```

---

## Step 3: Initialise and Apply

```bash
cd infra/terraform/

terraform init    # Downloads providers; connects to Spaces backend

terraform plan    # Review what will be created — no changes made yet
```

Due to a bootstrap ordering constraint (`kubernetes_manifest` requires the
cluster API during plan), apply must be run in **two passes**:

**Pass 1** — cluster and registry only:
```bash
terraform apply \
  -target=digitalocean_kubernetes_cluster.infodays \
  -target=digitalocean_container_registry.infodays \
  -target=digitalocean_container_registry_docker_credentials.pull
```

**Pass 2** — everything else:
```bash
terraform apply   # Provisions remaining ~21 resources; takes ~10–15 minutes total
```

Terraform provisions in this order (managed by the dependency graph):
1. DOKS cluster + DOCR registry (Pass 1)
2. Kubernetes namespaces + PodSecurity labels + NetworkPolicies
3. NGINX Ingress Controller (Helm)
4. DigitalOcean DNS zones + A-records (after LB IP is available)
5. cert-manager (Helm) + ClusterIssuer + Certificates

---

## Step 4: Verify

After `terraform apply` completes, run the validation suite:

```bash
# Export kubeconfig
terraform -chdir=infra/terraform output -raw kubeconfig | base64 -d > /tmp/infodays-kubeconfig.yaml
export KUBECONFIG=/tmp/infodays-kubeconfig.yaml

# Run all validation scripts
bash infra/tests/validate-cluster.sh
bash infra/tests/validate-network-isolation.sh
bash infra/tests/validate-tls.sh
```

Expected output: all checks pass (✅). Any failure is a blocking issue — do
not proceed to Phase 2 until resolved.

**Manual spot-checks**:

```bash
# All three namespaces present
kubectl get namespaces ctfd challenges monitoring

# PodSecurity labels on challenges namespace
kubectl get namespace challenges -o yaml | grep pod-security

# NetworkPolicies exist
kubectl get networkpolicy -n ctfd
kubectl get networkpolicy -n challenges

# Ingress controller running
kubectl get pods -n ingress-nginx

# cert-manager issued both certificates
kubectl get certificate -n ctfd
kubectl get certificate -n ingress-nginx

# TLS valid in browser equivalent
openssl s_client -connect ctfd.infodays.net:443 -servername ctfd.infodays.net </dev/null 2>/dev/null | openssl x509 -noout -subject -dates
```

---

## Teardown (end of event)

```bash
cd infra/terraform/
terraform destroy    # Destroys cluster, registry, DNS records, LB
```

The Spaces state bucket is NOT destroyed by `terraform destroy` (it is managed
by the bootstrap module). Delete it manually after teardown if desired.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `terraform apply` fails on DNS record | LB IP not yet assigned | Re-run apply; DO LB provisioning can take 3–5 min |
| Certificate stays in `Pending` | Subdomain NS delegation missing or DigitalOcean zones not created | Verify Cloudflare has NS records for `ctfd.infodays.net` and `challenges.infodays.net` → DigitalOcean. Ensure `terraform apply` has run (creates the DO zones). Both must exist. |
| Pod rejected by admission controller | PodSecurity standard violation | Check pod spec: must run as uid=1000, no root |
| Image pull fails in challenges namespace | DOCR registry integration not applied | Verify `registry_integration` attribute on cluster |
| Challenge pod reaches ctfd namespace | NetworkPolicy not applied | `kubectl get netpol -n challenges`; re-apply TF |
