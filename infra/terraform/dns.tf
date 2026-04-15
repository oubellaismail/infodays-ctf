# DigitalOcean DNS zones for the delegated subdomains.
# NS records pointing ctfd.infodays.net and challenges.infodays.net at these
# nameservers must be added in NS1 (the authoritative DNS for infodays.net)
# so that Let's Encrypt DNS-01 challenges and A-record lookups resolve here.

# ── SendGrid domain verification records ──────────────────────────────────────
# Required for send-credentials.py to send from noreply@infodays.net.
#
# HOW TO GET THESE VALUES:
#   1. SendGrid dashboard → Settings → Sender Authentication → Authenticate a Domain
#   2. Enter "infodays.net" and follow the wizard
#   3. SendGrid gives you 3 CNAME records — fill in the values below
#   4. Run: terraform apply -target=digitalocean_record.sendgrid_em \
#                           -target=digitalocean_record.sendgrid_dkim_s1 \
#                           -target=digitalocean_record.sendgrid_dkim_s2
#   5. Click "Verify" in SendGrid dashboard (propagation takes ~5 min)
#
# NOTE: These records go on the infodays.net root domain in NS1 (not on the
# ctfd/challenges subzones). If your NS1 setup delegates only subzones to DO,
# add these records directly in NS1 instead of using Terraform.

variable "sendgrid_em_cname" {
  description = "SendGrid em<id>.infodays.net CNAME value (from SendGrid dashboard)"
  default     = "FILL_IN_FROM_SENDGRID"
}

variable "sendgrid_dkim_s1" {
  description = "SendGrid s1._domainkey CNAME value (from SendGrid dashboard)"
  default     = "FILL_IN_FROM_SENDGRID"
}

variable "sendgrid_dkim_s2" {
  description = "SendGrid s2._domainkey CNAME value (from SendGrid dashboard)"
  default     = "FILL_IN_FROM_SENDGRID"
}

variable "sendgrid_em_subdomain" {
  description = "SendGrid em subdomain prefix (e.g. 'em1234' from SendGrid dashboard)"
  default     = "FILL_IN_FROM_SENDGRID"
}

# Uncomment these resources once you have the values from the SendGrid dashboard:
#
# resource "digitalocean_record" "sendgrid_em" {
#   domain = "infodays.net"   # must exist as a digitalocean_domain resource
#   type   = "CNAME"
#   name   = var.sendgrid_em_subdomain
#   value  = "${var.sendgrid_em_cname}."
#   ttl    = 300
# }
#
# resource "digitalocean_record" "sendgrid_dkim_s1" {
#   domain = "infodays.net"
#   type   = "CNAME"
#   name   = "s1._domainkey"
#   value  = "${var.sendgrid_dkim_s1}."
#   ttl    = 300
# }
#
# resource "digitalocean_record" "sendgrid_dkim_s2" {
#   domain = "infodays.net"
#   type   = "CNAME"
#   name   = "s2._domainkey"
#   value  = "${var.sendgrid_dkim_s2}."
#   ttl    = 300
# }
resource "digitalocean_domain" "ctfd" {
  name = "ctfd.infodays.net"
}

resource "digitalocean_domain" "challenges" {
  name = "challenges.infodays.net"
}

resource "digitalocean_record" "ctfd_a" {
  domain = digitalocean_domain.ctfd.name
  type   = "A"
  name   = "@"
  value  = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300

  depends_on = [data.kubernetes_service.ingress_nginx_lb]
}

resource "digitalocean_record" "challenges_wildcard_a" {
  domain = digitalocean_domain.challenges.name
  type   = "A"
  name   = "*"
  value  = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300

  depends_on = [data.kubernetes_service.ingress_nginx_lb]
}

# Apex A records for TCP challenges: nc challenges.infodays.net <nodeport>
# Dynamically resolved from cluster nodes via DOKS tag — no hardcoded IPs.
# Run `terraform apply` after node pool changes to refresh.
data "digitalocean_droplets" "workers" {
  filter {
    key    = "tags"
    values = ["k8s:${digitalocean_kubernetes_cluster.infodays.id}"]
    all    = false
  }
}

resource "digitalocean_record" "challenges_apex_a" {
  count  = length(data.digitalocean_droplets.workers.droplets)
  domain = digitalocean_domain.challenges.name
  type   = "A"
  name   = "@"
  value  = data.digitalocean_droplets.workers.droplets[count.index].ipv4_address
  ttl    = 60
}
