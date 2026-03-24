# Bootstrap: Create DigitalOcean Spaces bucket for Terraform state
# Run this ONCE before initializing infra/terraform/
# Uses local state (not stored in the bucket being created)

terraform {
  required_version = ">= 1.5"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

variable "do_token" {
  type        = string
  sensitive   = true
  description = "DigitalOcean API token"
}

variable "do_spaces_access_key" {
  type        = string
  sensitive   = true
  description = "DigitalOcean Spaces access key"
}

variable "do_spaces_secret_key" {
  type        = string
  sensitive   = true
  description = "DigitalOcean Spaces secret key"
}

provider "digitalocean" {
  token             = var.do_token
  spaces_access_id  = var.do_spaces_access_key
  spaces_secret_key = var.do_spaces_secret_key
}

resource "digitalocean_spaces_bucket" "tfstate" {
  name   = "infodays-tfstate"
  region = "fra1"
  acl    = "private"

  versioning {
    enabled = true
  }
}

output "bucket_name" {
  value       = digitalocean_spaces_bucket.tfstate.name
  description = "Name of the created Spaces bucket"
}
