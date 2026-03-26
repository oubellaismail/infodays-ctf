# Default-deny policies for all namespaces
resource "kubernetes_network_policy" "default_deny_ctfd" {
  metadata {
    name      = "default-deny-all"
    namespace = "ctfd"
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }

  depends_on = [kubernetes_namespace.ctfd]
}

resource "kubernetes_network_policy" "default_deny_challenges" {
  metadata {
    name      = "default-deny-all"
    namespace = "challenges"
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }

  depends_on = [kubernetes_namespace.challenges]
}

resource "kubernetes_network_policy" "default_deny_monitoring" {
  metadata {
    name      = "default-deny-all"
    namespace = "monitoring"
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }

  depends_on = [kubernetes_namespace.monitoring]
}

# Allowlist policies for challenges namespace
resource "kubernetes_network_policy" "allow_ingress_to_challenges" {
  metadata {
    name      = "allow-ingress-to-challenges"
    namespace = "challenges"
  }

  spec {
    pod_selector {}

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "ingress-nginx"
          }
        }
      }

      ports {
        port     = "8080"
        protocol = "TCP"
      }

      ports {
        port     = "1337"
        protocol = "TCP"
      }

      ports {
        port     = "4444"
        protocol = "TCP"
      }
    }

    policy_types = ["Ingress"]
  }

  depends_on = [kubernetes_namespace.challenges]
}

resource "kubernetes_network_policy" "allow_challenges_egress_dns" {
  metadata {
    name      = "allow-challenges-egress-dns"
    namespace = "challenges"
  }

  spec {
    pod_selector {}

    egress {
      to {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "kube-system"
          }
        }
      }

      ports {
        port     = "53"
        protocol = "UDP"
      }

      ports {
        port     = "53"
        protocol = "TCP"
      }
    }

    policy_types = ["Egress"]
  }

  depends_on = [kubernetes_namespace.challenges]
}

# Allowlist policies for ctfd namespace
resource "kubernetes_network_policy" "allow_ctfd_mysql" {
  metadata {
    name      = "allow-ctfd-mysql"
    namespace = "ctfd"
  }

  spec {
    pod_selector {
      match_labels = {
        app = "mysql"
      }
    }

    ingress {
      from {
        pod_selector {
          match_labels = {
            app = "ctfd"
          }
        }
      }

      ports {
        port     = "3306"
        protocol = "TCP"
      }
    }

    policy_types = ["Ingress"]
  }

  depends_on = [kubernetes_namespace.ctfd]
}

resource "kubernetes_network_policy" "allow_ctfd_redis" {
  metadata {
    name      = "allow-ctfd-redis"
    namespace = "ctfd"
  }

  spec {
    pod_selector {
      match_labels = {
        app = "redis"
      }
    }

    ingress {
      from {
        pod_selector {
          match_labels = {
            app = "ctfd"
          }
        }
      }

      ports {
        port     = "6379"
        protocol = "TCP"
      }
    }

    policy_types = ["Ingress"]
  }

  depends_on = [kubernetes_namespace.ctfd]
}

resource "kubernetes_network_policy" "allow_ctfd_egress_internet" {
  metadata {
    name      = "allow-ctfd-egress-internet"
    namespace = "ctfd"
  }

  spec {
    pod_selector {}

    egress {
      to {
        ip_block {
          cidr = "0.0.0.0/0"
        }
      }

      ports {
        port     = "443"
        protocol = "TCP"
      }
    }

    policy_types = ["Egress"]
  }

  depends_on = [kubernetes_namespace.ctfd]
}

resource "kubernetes_network_policy" "allow_ingress_to_ctfd" {
  metadata {
    name      = "allow-ingress-to-ctfd"
    namespace = "ctfd"
  }

  spec {
    pod_selector {}

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "ingress-nginx"
          }
        }
      }

      ports {
        port     = "8000"
        protocol = "TCP"
      }
    }

    policy_types = ["Ingress"]
  }

  depends_on = [kubernetes_namespace.ctfd]
}
