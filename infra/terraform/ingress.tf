resource "kubernetes_namespace" "ingress_nginx" {
  metadata {
    name = "ingress-nginx"
  }

  depends_on = [digitalocean_kubernetes_cluster.infodays]
}

resource "helm_release" "ingress_nginx" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  namespace  = "ingress-nginx"

  create_namespace = false
  wait             = true
  timeout          = 600

  set {
    name  = "controller.service.type"
    value = "LoadBalancer"
  }

  set {
    name  = "controller.replicaCount"
    value = "1"
  }

  # Enable TCP services ConfigMap so bulk_spawn can register TCP challenge ports
  set {
    name  = "controller.extraArgs.tcp-services-configmap"
    value = "ingress-nginx/tcp-services"
  }

  depends_on = [kubernetes_namespace.ingress_nginx]
}

data "kubernetes_service" "ingress_nginx_lb" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }

  depends_on = [helm_release.ingress_nginx]
}

output "ingress_lb_ip" {
  value       = data.kubernetes_service.ingress_nginx_lb.status[0].load_balancer[0].ingress[0].ip
  description = "Public IP of the NGINX Ingress load balancer"
}
