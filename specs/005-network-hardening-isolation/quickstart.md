# Quickstart: Network Hardening & Isolation

**Branch**: `005-network-hardening-isolation`
**Date**: 2026-03-26

This guide explains how to apply Phase 5 hardening to a running cluster and verify that isolation is working correctly.

## Prerequisites

- Phases 1–4 fully applied (cluster running, CTFd + controller deployed, challenge images in DOCR)
- `kubectl` configured for the `infodays-ctf` DOKS cluster
- `DIGITALOCEAN_TOKEN` set for Terraform
- At least one challenge deployment active in the `challenges` namespace for cross-team test validation

---

## Step 1: Apply the Terraform fix (external HTTPS egress scoping)

The existing `allow-ctfd-egress-internet` policy allows all ctfd pods to reach external HTTPS. This must be scoped to controller pods only.

```bash
terraform -chdir=infra/terraform apply \
  -target=kubernetes_network_policy.allow_ctfd_egress_internet \
  -auto-approve
```

Verify:
```bash
kubectl get networkpolicy allow-ctfd-egress-internet -n ctfd -o yaml \
  | grep -A5 podSelector
# Expected: matchLabels: app: controller-api
```

---

## Step 2: Apply RBAC (controller update + daemon creation)

```bash
# Update controller RBAC (adds missing verbs)
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml

# Create daemon RBAC (new)
kubectl apply -f k8s/rbac/challenge-daemon-rbac.yaml
```

Verify permissions:
```bash
kubectl auth can-i list pods -n ctfd \
  --as=system:serviceaccount:ctfd:ctf-controller
# Expected: no

kubectl auth can-i delete deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: no

kubectl auth can-i patch deployments -n challenges \
  --as=system:serviceaccount:ctfd:ctf-daemon
# Expected: yes
```

---

## Step 3: Apply standalone network policy YAMLs (optional — Terraform is authoritative)

The `k8s/network-policies/` files are kubectl-applicable equivalents of the Terraform policies. Apply them only if you need to recover from a Terraform state drift or apply manually without Terraform.

```bash
kubectl apply -f k8s/network-policies/
```

---

## Step 4: Verify PSS labels are applied

PSS labels are managed by Terraform (`infra/terraform/namespaces.tf`). Verify they are present:

```bash
kubectl get namespace challenges -o jsonpath='{.metadata.labels}' | jq
# Expected: pod-security.kubernetes.io/enforce: restricted

kubectl get namespace ctfd -o jsonpath='{.metadata.labels}' | jq
# Expected: pod-security.kubernetes.io/enforce: baseline
```

To patch manually if needed:
```bash
kubectl apply -f k8s/pod-security/namespace-labels.yaml
```

---

## Step 5: Run the isolation test suite

```bash
bash scripts/run-isolation-tests.sh
```

Expected output:
```
[PASS] test-deny-ctfd       — connection to ctfd namespace blocked
[PASS] test-deny-cross-team — cross-team pod access blocked
[PASS] test-deny-kube-api   — Kubernetes API access blocked
[PASS] test-deny-metadata   — DO metadata service blocked

All 4 isolation tests passed.
```

Any FAIL output means a network policy is missing or misconfigured. Check the policy for the relevant blocked path using the allowlist contract at `specs/005-network-hardening-isolation/contracts/network-policy-allowlist.md`.

---

## Step 6: Verify PSS enforcement

Attempt to deploy a privileged pod — it should be rejected:

```bash
kubectl run test-privileged \
  --image=alpine \
  --overrides='{"spec":{"containers":[{"name":"test","image":"alpine","securityContext":{"privileged":true}}]}}' \
  -n challenges
# Expected: Error from server (Forbidden): ... violates PodSecurity "restricted"
```

---

## Rollback

If isolation policies break legitimate traffic:

1. Identify the broken flow from the error logs or connection failures
2. Cross-reference with `contracts/network-policy-allowlist.md` — the flow should be listed there
3. If a policy is missing, create it; if a policy is over-blocking, fix the pod selector or port
4. **Do NOT** remove the default-deny baseline — fix the allow rule instead

For Terraform-managed policies:
```bash
terraform -chdir=infra/terraform apply -target=kubernetes_network_policy.<name>
```

For kubectl-managed policies:
```bash
kubectl apply -f k8s/network-policies/<file>.yaml
```
