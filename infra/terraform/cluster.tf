data "digitalocean_kubernetes_versions" "available" {
}

resource "digitalocean_kubernetes_cluster" "infodays" {
  name    = var.cluster_name
  region  = var.cluster_region
  version = data.digitalocean_kubernetes_versions.available.latest_version

  auto_upgrade  = false
  surge_upgrade = false
  ha            = false

  node_pool {
    name       = "infodays-workers"
    size       = var.node_size
    auto_scale = true
    min_nodes  = var.node_min
    max_nodes  = var.node_max
    labels = {
      role = "worker"
    }
  }
}

# Allowlisted NodePort access for challenge workers.
# Leaving challenge_nodeport_source_addresses empty disables direct internet
# access to NodePorts entirely, which is the safer default.
# DigitalOcean Cloud Firewalls currently do not expose a traffic-log setting in
# the Terraform resource, so logging must be implemented at another layer.
# Applied via the k8s:worker tag that DOKS sets on all worker droplets.
resource "digitalocean_firewall" "nodeport_access" {
  count = length(var.challenge_nodeport_source_addresses) > 0 ? 1 : 0

  name = "ctf-challenges-nodeport-access"
  tags = ["k8s:worker"]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "30000-32767"
    source_addresses = var.challenge_nodeport_source_addresses
  }
}
