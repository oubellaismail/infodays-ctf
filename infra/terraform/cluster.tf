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
