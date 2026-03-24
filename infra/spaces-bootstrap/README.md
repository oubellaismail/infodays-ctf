# Spaces Bootstrap

This is a **one-time bootstrap step** that must be run ONCE before initializing the main Terraform module.

## Purpose

Create the DigitalOcean Spaces bucket (`infodays-tfstate`) that will store the Terraform state for the main cluster module. This uses **local state** (not stored in the bucket being created).

## Prerequisites

- DigitalOcean API token with read/write permissions
- DigitalOcean Spaces access key and secret key
- Terraform ≥1.5 installed
- Valid credentials configured in `terraform.tfvars` (see below)

## Steps

### Step 1: Create `terraform.tfvars`

Copy this file contents:

```hcl
do_token               = "dop_v1_..."  # Your DO API token
do_spaces_access_key   = "..."         # Your Spaces access key
do_spaces_secret_key   = "..."         # Your Spaces secret key
```

### Step 2: Bootstrap

```bash
cd infra/spaces-bootstrap/

terraform init

terraform apply
```

Confirm and verify that the output shows the bucket name `infodays-tfstate`.

### Step 3: Proceed to Main Module

Once the bucket is created, move to `infra/terraform/` and follow the main module instructions.

## ⚠️ Important Notes

- This `terraform.tfvars` file is **local-only** for the bootstrap step. It must NOT be committed to git.
- The bucket is created with versioning enabled — this is intentional for backup safety.
- The bucket ACL is `private` — only authenticated users with valid credentials can access it.
- The main Terraform module will use this bucket as its state backend.
- **Do NOT delete the Spaces bucket** while the cluster exists — it stores the state.

## Cleanup (Optional)

If you later want to destroy the state bucket:

```bash
terraform destroy
```

**⚠️ Warning**: Only destroy the bucket AFTER the main cluster has been destroyed and is no longer needed.
