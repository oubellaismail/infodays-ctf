variable "do_token" {
  type        = string
  sensitive   = true
  description = "DigitalOcean API token with read/write permissions"
}

# NOTE: Spaces credentials (access key / secret key) are NOT Terraform variables.
# The S3 backend cannot use variable interpolation. Supply them as environment
# variables before running terraform init:
#   export AWS_ACCESS_KEY_ID="<your-spaces-access-key>"
#   export AWS_SECRET_ACCESS_KEY="<your-spaces-secret-key>"

variable "do_dns_token" {
  type        = string
  sensitive   = true
  description = "DigitalOcean API token scoped to DNS management (used by cert-manager)"
}

variable "letsencrypt_email" {
  type        = string
  description = "Email address for Let's Encrypt ACME registration"
}

variable "cluster_name" {
  type        = string
  default     = "infodays-ctf"
  description = "DOKS cluster name"
}

variable "cluster_region" {
  type        = string
  default     = "fra1"
  description = "DOKS cluster region (must be fra1 per constitution)"
}

variable "cluster_version" {
  type        = string
  default     = ""
  description = "DOKS Kubernetes version prefix filter (empty = latest available)"
}

variable "node_size" {
  type        = string
  default     = "s-4vcpu-8gb"
  description = "Node pool droplet size (Phase 7: 5 × s-4vcpu-8gb general pool for 50-team support)"
}

variable "node_min" {
  type        = number
  default     = 3
  description = "Minimum nodes in autoscaling pool (scales down during quiet periods)"
}

variable "node_max" {
  type        = number
  default     = 8
  description = "Maximum nodes in autoscaling pool (scales up for event peak / surprise load)"
}

variable "registry_name" {
  type        = string
  default     = "infodays-registry"
  description = "DOCR registry name"
}

variable "registry_tier" {
  type        = string
  default     = "starter"
  description = "DOCR subscription tier (must be starter per constitution)"
}

variable "use_letsencrypt_staging" {
  type        = bool
  default     = false
  description = "Use Let's Encrypt staging server (set true for testing to avoid rate limits)"
}
