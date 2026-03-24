# Contract: Terraform Output Values

**Module**: `infra/terraform/`
**Feature**: 001-cluster-network-foundation
**Date**: 2026-03-21

These are the values exported by `terraform output` after a successful apply.
Downstream phases (Phase 2: CTFd stack, Phase 3: challenge deployment) consume
these values to configure their own resources.

---

## Outputs

| Output name | Type | Description | Sensitive |
|---|---|---|---|
| `cluster_id` | `string` | DOKS cluster UUID | No |
| `cluster_endpoint` | `string` | Kubernetes API server URL (`https://...`) | No |
| `cluster_name` | `string` | Cluster name as provisioned | No |
| `kubeconfig` | `string` | Base64-encoded kubeconfig for `kubectl` access | **Yes** |
| `registry_endpoint` | `string` | DOCR registry hostname (`registry.digitalocean.com/infodays-registry`) | No |
| `registry_name` | `string` | DOCR registry name | No |
| `ingress_lb_ip` | `string` | Public IP of the NGINX Ingress load balancer | No |
| `ctfd_namespace` | `string` | `"ctfd"` — canonical name for use in downstream configs | No |
| `challenges_namespace` | `string` | `"challenges"` — canonical name | No |

---

## Consumption by Downstream Phases

| Phase | Consumes | Purpose |
|---|---|---|
| Phase 2 (CTFd stack) | `kubeconfig`, `registry_endpoint`, `ctfd_namespace` | Deploy CTFd, MySQL, Redis |
| Phase 3 (Challenge deployment) | `kubeconfig`, `registry_endpoint`, `challenges_namespace` | Build and push challenge images; deploy Deployments |
| Phase 4 (Controller) | `kubeconfig`, `cluster_endpoint`, `ctfd_namespace` | Controller API and lifetime daemon configuration |

---

## Usage

```bash
# Get a single output value
terraform -chdir=infra/terraform output -raw ingress_lb_ip

# Get kubeconfig and write to file (sensitive — handle carefully)
terraform -chdir=infra/terraform output -raw kubeconfig | base64 -d > ~/.kube/infodays-ctf.yaml
```

**Security rule**: `kubeconfig` is a sensitive output. It MUST NOT be printed
to logs, stored unencrypted, or committed to git.
