#!/bin/bash
# teardown-challenges.sh - Delete all CTF controller-managed resources

set -euo pipefail

echo "WARNING: This will delete ALL resources labeled managed-by=ctf-controller in the challenges namespace."
read -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

echo "Deleting Ingress resources..."
kubectl delete ingress -n challenges -l managed-by=ctf-controller

echo "Deleting Service resources..."
kubectl delete svc -n challenges -l managed-by=ctf-controller

echo "Deleting Deployment resources..."
kubectl delete deploy -n challenges -l managed-by=ctf-controller

echo "Deleting Secret resources..."
kubectl delete secret -n challenges -l managed-by=ctf-controller

echo "Teardown complete. Verifying..."
remaining=$(kubectl get all -n challenges -l managed-by=ctf-controller 2>/dev/null | wc -l)
if [ "$remaining" -le 1 ]; then
  echo "✓ All managed resources deleted."
else
  echo "⚠ Warning: Some resources may still exist. Manual cleanup may be required."
fi

echo ""
echo "Note: TCP ConfigMap cleanup in ingress-nginx/tcp-services must be done manually."
