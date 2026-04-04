# Phase 7: Dedicated MySQL Node Pool
# NOTE: m-2vcpu-16gb has no capacity in fra1 — pool disabled, MySQL runs on general pool.
# Re-enable when capacity is available.
#
# resource "digitalocean_kubernetes_node_pool" "mysql" {
#   cluster_id = digitalocean_kubernetes_cluster.infodays.id
#   name       = "mysql-pool"
#   size       = "m-2vcpu-16gb"
#   node_count = 1
#   labels     = { role = "mysql" }
#   taint {
#     key    = "workload"
#     value  = "mysql"
#     effect = "NoSchedule"
#   }
# }
