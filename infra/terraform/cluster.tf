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
    node_count = var.node_count
    labels = {
      role = "worker"
    }
  }
}

# Open NodePort range on worker nodes so TCP challenges are reachable from
# the internet: nc challenges.infodays.net <nodeport>
# Applied via the k8s:worker tag that DOKS sets on all worker droplets.
resource "digitalocean_firewall" "nodeport_access" {
  name = "ctf-challenges-nodeport-access"
  tags = ["k8s:worker"]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "30000-32767"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }
}
