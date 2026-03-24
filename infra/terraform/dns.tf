# DigitalOcean DNS zones for the delegated subdomains.
# NS records pointing ctfd.infodays.net and challenges.infodays.net at these
# nameservers must be added in NS1 (the authoritative DNS for infodays.net)
# so that Let's Encrypt DNS-01 challenges and A-record lookups resolve here.
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
