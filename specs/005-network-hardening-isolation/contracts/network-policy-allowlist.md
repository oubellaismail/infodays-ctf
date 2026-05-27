# Contract: Network Policy Allowlist

**Feature**: 005-network-hardening-isolation
**Date**: 2026-03-26

This contract defines the complete authoritative allowlist for both namespaces. All traffic NOT listed here is blocked by the default-deny baseline. Implementations MUST NOT add allow rules beyond this list without a spec amendment.

---

## challenges namespace — Allowlist

| Direction | From | To | Ports | Condition |
|-----------|------|----|-------|-----------|
| Ingress | Pods in `ingress-nginx` namespace | All challenge pods | 8080/TCP, 1337/TCP, 4444/TCP | Always (via ingress) |
| Ingress | Any source (NodePort / kube-proxy) | All challenge pods | 8080/TCP, 1337/TCP, 4444/TCP | Always (direct NodePort) |
| Egress | All challenge pods | Pods in `kube-system` namespace | 53/UDP, 53/TCP | Always (DNS) |

> **Note on NodePort ingress**: HTTP (8080), TCP pwn (1337), and misc (4444) challenges all use NodePort directly via `challenges.infodays.net:{port}`. NodePort traffic originates from kube-proxy on the node itself — not from the `ingress-nginx` namespace — so a separate no-source-selector policy (`allow-nodeport-to-challenges`) is required. Without it, `default-deny-all` silently drops all direct NodePort connections.

**Everything else is BLOCKED**, including:
- Challenge pod → ctfd namespace (any port)
- Challenge pod → other challenge pods (any port, same or different team)
- Challenge pod → 10.96.0.1/32:443 (Kubernetes API)
- Challenge pod → 169.254.169.254/32 (DigitalOcean metadata)
- Challenge pod → any external IP
- External → challenge pod on any port outside 8080, 1337, 4444

---

## ctfd namespace — Allowlist

| Direction | From | To | Ports | Condition |
|-----------|------|----|-------|-----------|
| Ingress | Pods in `ingress-nginx` namespace | All ctfd pods | 8000/TCP | Always |
| Ingress | `app: ctfd` pods | `app: controller-api` pods | 5000/TCP | CTFd → controller |
| Egress | All ctfd pods | Pods in `kube-system` namespace | 53/UDP, 53/TCP | Always (DNS) |
| Egress | `app: ctfd` pods | `app: mysql` pods (same ns) | 3306/TCP | CTFd → database |
| Egress | `app: ctfd` pods | `app: redis` pods (same ns) | 6379/TCP | CTFd → cache |
| Egress | `app: ctfd` pods | `app: controller-api` pods (same ns) | 5000/TCP | CTFd → controller proxy |
| Egress | `app: controller-api` pods | Kubernetes API server IP | 443/TCP | Controller → K8s API |
| Egress | `app: controller-api` pods | 0.0.0.0/0 | 443/TCP | Controller → external HTTPS |

> **Scoping note on external HTTPS**: Only `app: controller-api` pods may reach external HTTPS. All other ctfd namespace pods (CTFd, MySQL, Redis, daemon) are blocked from external HTTPS egress.

---

## Namespace Selector Reference

| Namespace | Label Used in NetworkPolicy |
|-----------|---------------------------|
| `ingress-nginx` | `kubernetes.io/metadata.name: ingress-nginx` |
| `kube-system` | `kubernetes.io/metadata.name: kube-system` |

---

## Policy Implementation Mapping

| Policy Name | Namespace | Implementation Location |
|-------------|-----------|------------------------|
| `default-deny-all` | challenges | `infra/terraform/network-policies.tf` + `k8s/network-policies/challenges-default-deny.yaml` |
| `allow-ingress-to-challenges` | challenges | `infra/terraform/network-policies.tf` + `k8s/network-policies/challenges-allow-ingress.yaml` |
| `allow-nodeport-to-challenges` | challenges | `k8s/network-policies/challenges-allow-nodeport.yaml` (ports 8080, 1337, 4444; no source selector) |
| `allow-challenges-egress-dns` | challenges | `infra/terraform/network-policies.tf` + `k8s/network-policies/challenges-allow-dns.yaml` |
| `default-deny-all` | ctfd | `infra/terraform/network-policies.tf` + `k8s/network-policies/ctfd-default-deny.yaml` |
| `allow-ingress-to-ctfd` | ctfd | `infra/terraform/network-policies.tf` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-ctfd-egress-mysql` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-ctfd-egress-redis` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-ctfd-egress-controller` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-ctfd-to-controller-ingress` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-ctfd-egress-dns` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-internal.yaml` |
| `allow-controller-egress-k8s-api` | ctfd | `k8s/ctfd/networkpolicy.yaml` + `k8s/network-policies/ctfd-allow-controller-egress.yaml` |
| `allow-ctfd-egress-internet` | ctfd | `infra/terraform/network-policies.tf` (UPDATE scope) + `k8s/network-policies/ctfd-allow-controller-egress.yaml` |
| `allow-controller-egress-ctfd` | ctfd | `k8s/ctfd/networkpolicy.yaml` (controller → ctfd pods on 8000) |
| `allow-ctfd-ingress-controller` | ctfd | `k8s/ctfd/networkpolicy.yaml` (ctfd pods accept from controller on 8000) |
