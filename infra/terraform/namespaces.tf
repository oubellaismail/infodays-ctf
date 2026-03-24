resource "kubernetes_namespace" "ctfd" {
  metadata {
    name = "ctfd"
    labels = {
      "pod-security.kubernetes.io/enforce"         = "baseline"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/warn"            = "baseline"
      "pod-security.kubernetes.io/warn-version"    = "latest"
    }
  }

  depends_on = [digitalocean_kubernetes_cluster.infodays]
}

resource "kubernetes_namespace" "challenges" {
  metadata {
    name = "challenges"
    labels = {
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/warn"            = "restricted"
      "pod-security.kubernetes.io/warn-version"    = "latest"
    }
  }

  depends_on = [digitalocean_kubernetes_cluster.infodays]
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }

  depends_on = [digitalocean_kubernetes_cluster.infodays]
}
