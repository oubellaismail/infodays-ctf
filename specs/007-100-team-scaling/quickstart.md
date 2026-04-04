# Quickstart: 100-Team Scaling (400 VUs)

**Feature**: 007-100-team-scaling | **Date**: 2026-04-02

## Prerequisites

- Existing InfoDays CTF cluster running (Phases 1-6 complete)
- `doctl` authenticated with DigitalOcean
- `kubectl` configured for the `infodays-ctf` cluster
- `terraform` ≥1.5 with state backend configured
- `k6` installed for load testing
- 100 team accounts created in CTFd (or script to create them)

## Step-by-Step Deployment

### 1. Provision Dedicated MySQL Node Pool

```bash
# Add mysql-node-pool.tf to infra/terraform/ (see data-model.md for config)
# Update cluster.tf with new general pool sizing

terraform -chdir=infra/terraform init \
  -backend-config="access_key=$AWS_ACCESS_KEY_ID" \
  -backend-config="secret_key=$AWS_SECRET_ACCESS_KEY"

# Apply node pool changes first
terraform -chdir=infra/terraform apply \
  -target=digitalocean_kubernetes_node_pool.mysql \
  -target=digitalocean_kubernetes_cluster.infodays \
  -auto-approve

# Update kubeconfig for new cluster state
doctl kubernetes cluster kubeconfig save infodays-ctf
```

### 2. Migrate MySQL to Dedicated Node

```bash
# Apply updated MySQL StatefulSet (toleration + nodeSelector + increased resources)
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml

# Verify MySQL rescheduled to dedicated node
kubectl get pods -n ctfd -l app=mysql -o wide
# Should show node from mysql-pool
```

### 3. Deploy ProxySQL

```bash
# Apply ProxySQL config and deployment
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl apply -f k8s/ctfd/proxysql-deployment.yaml

# Verify ProxySQL is running
kubectl get pods -n ctfd -l app=proxysql
# Should show 2/2 ready

# Verify ProxySQL can reach MySQL
kubectl exec -n ctfd deploy/proxysql -- \
  mysql -h 127.0.0.1 -P 6032 -u admin -padmin \
  -e "SELECT * FROM stats_mysql_connection_pool"
```

### 4. Update Network Policies

```bash
# Apply updated network policies (removes direct CTFd→MySQL, adds ProxySQL rules)
kubectl apply -f k8s/ctfd/networkpolicy.yaml

# Verify CTFd can reach ProxySQL
kubectl exec -n ctfd deploy/ctfd -- \
  python -c "import socket; s=socket.create_connection(('proxysql', 6033)); print('OK'); s.close()"
```

### 5. Roll CTFd to 10 Replicas via ProxySQL

```bash
# Apply updated CTFd deployment (DATABASE_URL → proxysql, replicas → 10)
kubectl apply -f k8s/ctfd/deployment.yaml

# Wait for rollout
kubectl rollout status deployment/ctfd -n ctfd --timeout=300s

# Verify all replicas healthy
kubectl get pods -n ctfd -l app=ctfd
# Should show 10/10 ready
```

### 6. Verify End-to-End Connectivity

```bash
# Check CTFd can query through ProxySQL
kubectl logs -n ctfd deploy/ctfd --tail=20
# Should show normal startup, no MySQL connection errors

# Check ProxySQL stats
kubectl exec -n ctfd deploy/proxysql -- \
  mysql -h 127.0.0.1 -P 6032 -u admin -padmin \
  -e "SELECT srv_host, srv_port, ConnUsed, ConnFree, ConnOK, ConnERR FROM stats_mysql_connection_pool"
# ConnUsed should be < 50, ConnOK should be increasing
```

### 7. Pre-Spawn 100-Team Challenge Resources

```bash
# Ensure 100 teams exist in CTFd, then bulk spawn
kubectl exec -n ctfd deploy/controller-api -- python bulk_spawn.py

# Verify deployment count
kubectl get deployments -n challenges --no-headers | wc -l
# Should be ~1500 (100 teams × 15 challenges)
```

### 8. Run 400-VU Load Test

```bash
# Generate 100-team credentials JSON
# K6_CTF_TEAMS='[{"username":"team1","password":"...","team_id":"1"}, ...]'

k6 run \
  -e K6_CTF_URL=https://ctfd.infodays.net \
  -e K6_CTF_TEAMS="$K6_CTF_TEAMS" \
  tests/load/k6-ctf-scenario.js

# Expected: p95 < 3s, error rate < 1% over 45 minutes
```

## Rollback

If load test fails or platform is unstable:

```bash
# 1. Revert CTFd to direct MySQL connection (5 replicas)
kubectl apply -f k8s/ctfd/deployment.yaml.bak  # (save backup before changes)

# 2. Revert network policies
kubectl apply -f k8s/ctfd/networkpolicy.yaml.bak

# 3. Remove ProxySQL
kubectl delete -f k8s/ctfd/proxysql-deployment.yaml
kubectl delete -f k8s/ctfd/proxysql-configmap.yaml

# 4. Revert MySQL to shared node
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml.bak

# 5. Revert Terraform (node pools)
terraform -chdir=infra/terraform apply -auto-approve  # (with reverted .tf files)
```

## Verification Checklist

- [ ] MySQL running on dedicated node (`kubectl get pods -n ctfd -l app=mysql -o wide`)
- [ ] ProxySQL 2 replicas ready (`kubectl get pods -n ctfd -l app=proxysql`)
- [ ] CTFd 10 replicas ready (`kubectl get pods -n ctfd -l app=ctfd`)
- [ ] ProxySQL server connections < 50 (`stats_mysql_connection_pool`)
- [ ] 1,500 challenge Deployments created (`kubectl get deploy -n challenges | wc -l`)
- [ ] Load test passes: p95 < 3s, error < 1%
- [ ] CiliumNetworkPolicy + ClusterRole in version control
