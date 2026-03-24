# Contract: Terraform Input Variables

**Module**: `infra/terraform/`
**Feature**: 001-cluster-network-foundation
**Date**: 2026-03-21

These are the variables an operator MUST or MAY supply when running
`terraform apply`. Variables marked **Required** have no default and MUST be
provided (via `terraform.tfvars` or environment variable). Variables marked
**Optional** have a sensible default that satisfies the constitution.

---

## Required Variables

| Variable | Type | Description | Validation |
|---|---|---|---|
| `do_token` | `string` | DigitalOcean API token (read/write). Used for cluster, registry, and DNS. | Length > 0; sensitive |
| `do_dns_token` | `string` | DigitalOcean API token scoped to DNS management only. Used by cert-manager for DNS-01 ACME challenge. MAY be the same as `do_token`. | sensitive |
| `letsencrypt_email` | `string` | Email address for Let's Encrypt ACME registration. | Valid email; required |

**Spaces credentials are NOT Terraform variables.** The S3 backend cannot use
variable interpolation — supply them as environment variables before running
`terraform init`:

```bash
export AWS_ACCESS_KEY_ID="<your-spaces-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-spaces-secret-key>"
```

**Security rule**: None of these values MUST appear in any file committed to
git. Use `.tfvars` files (gitignored) or environment variables.

---

## Optional Variables (with constitution-safe defaults)

| Variable | Type | Default | Description | Constraint |
|---|---|---|---|---|
| `cluster_name` | `string` | `"infodays-ctf"` | DOKS cluster name | — |
| `cluster_region` | `string` | `"fra1"` | Cluster region | MUST be `"fra1"` per constitution |
| `cluster_version` | `string` | `""` | DOKS K8s version prefix filter. Empty string = latest available. | DOKS 1.28 is retired; use latest |
| `node_size` | `string` | `"s-4vcpu-8gb"` | Node pool droplet size | MUST NOT exceed `s-4vcpu-8gb` per constitution |
| `node_count` | `number` | `4` | Number of nodes in the pool | MUST NOT exceed 5 per constitution |
| `registry_name` | `string` | `"infodays-registry"` | DOCR registry name | — |
| `registry_tier` | `string` | `"starter"` | DOCR subscription tier | MUST be `"starter"` per constitution |
| `spaces_bucket_name` | `string` | `"infodays-tfstate"` | Spaces bucket for TF state | Pre-created by `spaces-bootstrap/` |
| `use_letsencrypt_staging` | `bool` | `false` | Use LE staging (avoids rate limits in testing) | Set `true` for test runs |

---

## Variable File Layout

```text
infra/terraform/
├── variables.tf          # Variable declarations (no values)
├── terraform.tfvars      # Operator-supplied values — GITIGNORED
└── terraform.tfvars.example  # Example file with placeholder values — committed
```

`terraform.tfvars.example` MUST contain only placeholder values
(e.g., `do_token = "YOUR_DO_API_TOKEN_HERE"`). Real values MUST NOT appear in
any committed file.
