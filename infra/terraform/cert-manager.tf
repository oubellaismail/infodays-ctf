resource "kubernetes_namespace" "cert_manager" {
  metadata {
    name = "cert-manager"
  }

  depends_on = [digitalocean_kubernetes_cluster.infodays]
}

resource "helm_release" "cert_manager" {
  name       = "cert-manager"
  repository = "https://charts.jetstack.io"
  chart      = "cert-manager"
  namespace  = "cert-manager"

  create_namespace = false
  wait             = true
  timeout          = 300

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [kubernetes_namespace.cert_manager]
}

resource "kubernetes_secret" "do_dns_token" {
  metadata {
    name      = "do-dns-token"
    namespace = "cert-manager"
  }

  type = "Opaque"

  data = {
    "access-token" = var.do_dns_token
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_manifest" "cluster_issuer" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"

    metadata = {
      name = "letsencrypt-prod"
    }

    spec = {
      acme = {
        server = var.use_letsencrypt_staging ? "https://acme-staging-v02.api.letsencrypt.org/directory" : "https://acme-v02.api.letsencrypt.org/directory"
        email  = var.letsencrypt_email

        privateKeySecretRef = {
          name = "letsencrypt-prod-account-key"
        }

        solvers = [
          {
            dns01 = {
              digitalocean = {
                tokenSecretRef = {
                  name = "do-dns-token"
                  key  = "access-token"
                }
              }
            }
          }
        ]
      }
    }
  }

  depends_on = [kubernetes_secret.do_dns_token]
}

resource "kubernetes_manifest" "cert_ctfd" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"

    metadata = {
      name      = "ctfd-tls"
      namespace = "ctfd"
    }

    spec = {
      dnsNames = ["ctfd.infodays.net"]

      issuerRef = {
        name = "letsencrypt-prod"
        kind = "ClusterIssuer"
      }

      secretName = "ctfd-tls-secret"
    }
  }

  depends_on = [
    kubernetes_manifest.cluster_issuer,
    kubernetes_namespace.ctfd
  ]
}

resource "kubernetes_manifest" "cert_challenges" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"

    metadata = {
      name      = "challenges-wildcard-tls"
      namespace = "ingress-nginx"
    }

    spec = {
      dnsNames = ["*.challenges.infodays.net"]

      issuerRef = {
        name = "letsencrypt-prod"
        kind = "ClusterIssuer"
      }

      secretName = "challenges-tls-secret"
    }
  }

  depends_on = [
    kubernetes_manifest.cluster_issuer,
    kubernetes_namespace.ingress_nginx
  ]
}
