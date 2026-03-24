resource "digitalocean_container_registry" "infodays" {
  name               = var.registry_name
  subscription_tier_slug = var.registry_tier
  region            = var.cluster_region
}

resource "digitalocean_container_registry_docker_credentials" "pull" {
  registry_name  = digitalocean_container_registry.infodays.name
  write          = false
  expiry_seconds = 0
}

resource "kubernetes_secret" "docr_pull_secret" {
  for_each = toset(["ctfd", "challenges"])

  metadata {
    name      = "docr-pull-secret"
    namespace = each.key
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = digitalocean_container_registry_docker_credentials.pull.docker_credentials
  }

  depends_on = [
    kubernetes_namespace.ctfd,
    kubernetes_namespace.challenges
  ]
}

resource "kubernetes_default_service_account" "patch_docr" {
  for_each = toset(["ctfd", "challenges"])

  metadata {
    namespace = each.key
  }

  image_pull_secret {
    name = "docr-pull-secret"
  }

  depends_on = [kubernetes_secret.docr_pull_secret]
}
