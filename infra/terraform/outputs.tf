output "cluster_id" {
  value       = digitalocean_kubernetes_cluster.infodays.id
  description = "DOKS cluster UUID"
}

output "cluster_endpoint" {
  value       = digitalocean_kubernetes_cluster.infodays.endpoint
  description = "Kubernetes API server URL"
}

output "cluster_name" {
  value       = digitalocean_kubernetes_cluster.infodays.name
  description = "Cluster name as provisioned"
}

output "kubeconfig" {
  value       = base64encode(digitalocean_kubernetes_cluster.infodays.kube_config[0].raw_config)
  sensitive   = true
  description = "Base64-encoded kubeconfig for kubectl access"
}

output "registry_endpoint" {
  value       = digitalocean_container_registry.infodays.server_url
  description = "DOCR registry hostname"
}

output "registry_name" {
  value       = digitalocean_container_registry.infodays.name
  description = "DOCR registry name"
}

output "ctfd_namespace" {
  value       = "ctfd"
  description = "Canonical name for ctfd namespace"
}

output "challenges_namespace" {
  value       = "challenges"
  description = "Canonical name for challenges namespace"
}
