# Event-safe dedicated MySQL node pool.
# Keeps the primary database off the shared worker nodes during the 12-hour CTF.
resource "digitalocean_kubernetes_node_pool" "mysql" {
  cluster_id = digitalocean_kubernetes_cluster.infodays.id
  name       = "mysql-pool"
  size       = "s-4vcpu-8gb"
  node_count = 1
  labels     = { role = "mysql" }

  taint {
    key    = "workload"
    value  = "mysql"
    effect = "NoSchedule"
  }
}
