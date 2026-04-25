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
  description = "Exact DOKS Kubernetes version. Empty selects latest; pin during event windows to avoid surprise upgrades."
}

variable "node_size" {
  type        = string
  default     = "s-4vcpu-8gb"
  description = "General worker pool droplet size for CTFd, controller, monitoring, and challenge workloads"
}

variable "node_min" {
  type        = number
  default     = 4
  description = "Minimum nodes in the general worker pool for the 60-user event profile"
}

variable "node_max" {
  type        = number
  default     = 4
  description = "Maximum nodes in the general worker pool; MySQL gets a separate dedicated node pool"
}

variable "challenge_nodeport_source_addresses" {
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
  description = "IPv4/IPv6 CIDRs allowed to reach challenge NodePorts. Defaults to public internet access because the platform serves challenge traffic through direct NodePorts."
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
