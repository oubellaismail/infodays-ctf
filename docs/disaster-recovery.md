# InfoDays CTF — Disaster Recovery Playbook

**Last updated**: 2026-04-14
**Audience**: Operations team. Keep this open alongside `event-day-runbook.md` during the event.

---

## Risk Summary

| Severity | Component | RTO | Data Loss? |
|----------|-----------|-----|------------|
| 🔴 Critical | MySQL primary crash + corrupted PVC | 10–15 min | Yes if no backup |
| 🔴 Critical | CTF_MASTER_SECRET lost | 1–10 min | Flags unrecoverable |
| 🔴 Critical | DOKS cluster destroyed | 20–30 min | No (MySQL on PVC) |
| 🟠 High | Terraform state corrupted | 30+ min | No |
| 🟠 High | nginx ingress crash | 1–2 min | No |
| 🟠 High | TLS certificate expired | 5 min | No |
| 🟡 Medium | MySQL OOM restart | 3–5 min | No (PVC survives) |
| 🟡 Medium | Redis crash | 1 min | Sessions only |
| 🟡 Medium | DNS stale after node autoscale | 5–10 min | No |
| 🟢 Low | CTFd / controller pods crash | <1 min | No (stateless) |

---

## Automated Backup Status

The `mysql-backup` CronJob runs every 30 minutes and uploads to:
```
s3://infodays-ctf-tfstate/backups/ctfd-backup-YYYY-MM-DDTHH-MM-SSZ.sql.gz
```

Retention: last 48 hours (auto-rotated). Pre-event and event-final backups are protected.

Check backup health:
```bash
# List last 5 backups
bash scripts/restore-mysql.sh --list | head -5

# Check CronJob status
kubectl get cronjob mysql-backup -n ctfd
kubectl get jobs -n ctfd --sort-by=.metadata.creationTimestamp | tail -5

# Check last job logs
kubectl logs -n ctfd -l job-name=$(kubectl get jobs -n ctfd --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}') --tail=20
```

---

## Scenario 1 — MySQL Crashed or Corrupted

### 1A — Pod crash (PVC intact, data fine)

Most common. The StatefulSet auto-restarts. Usually self-healing.

```bash
# Check
kubectl get pod mysql-0 -n ctfd
kubectl describe pod mysql-0 -n ctfd | tail -20

# If CrashLoopBackOff — force pod recreation (PVC survives)
kubectl delete pod mysql-0 -n ctfd
kubectl rollout status statefulset/mysql -n ctfd  # wait for Ready

# Verify MySQL is healthy
kubectl exec mysql-0 -n ctfd -- \
  mysqladmin status -u root -p"$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)"
```

**Expected RTO: 2–5 minutes.**

---

### 1B — Data corrupted (InnoDB crash recovery needed)

Symptoms: MySQL starts but tables return errors, CTFd shows DB errors in logs.

```bash
# Check for table errors
PASS=$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)
kubectl exec mysql-0 -n ctfd -- \
  mysqlcheck -u root -p"$PASS" --auto-repair ctfd

# If mysqlcheck can repair it, restart CTFd to clear connection pool
kubectl rollout restart deployment/ctfd -n ctfd
```

If mysqlcheck can't repair: **restore from backup**.

---

### 1C — Restore from backup

```bash
# Option 1: restore the most recent Spaces backup (recommended)
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  bash scripts/restore-mysql.sh --latest

# Option 2: restore a specific backup
bash scripts/restore-mysql.sh backups/ctfd-backup-2026-04-14T12-00-00Z.sql.gz

# Option 3: list available backups and pick one
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  bash scripts/restore-mysql.sh --list
```

The script:
1. Takes a live pre-restore snapshot before touching anything
2. Prompts for confirmation
3. Applies the restore
4. Flushes Redis (teams re-login, required after data rollback)
5. Reports row counts before/after

**Expected RTO: 10–15 minutes.**

---

### 1D — MySQL PVC destroyed (worst case)

If the `mysql-data-mysql-0` PVC is deleted, all data since the last backup is lost.

```bash
# Recreate StatefulSet — new PVC will be provisioned automatically
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml
kubectl rollout status statefulset/mysql -n ctfd

# Restore from backup
bash scripts/restore-mysql.sh --latest

# Recreate MySQL user for CTFd (backup only includes data, not grants)
PASS=$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)
CTFD_PASS=$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_PASSWORD}' | base64 -d)
kubectl exec mysql-0 -n ctfd -- mysql -u root -p"$PASS" -e "
  CREATE USER IF NOT EXISTS 'ctfd'@'%' IDENTIFIED BY '${CTFD_PASS}';
  GRANT ALL PRIVILEGES ON ctfd.* TO 'ctfd'@'%';
  FLUSH PRIVILEGES;
"

# Restart ProxySQL to reconnect
kubectl rollout restart deployment/proxysql -n ctfd
```

**Expected RTO: 15–20 minutes.**

---

## Scenario 2 — CTF_MASTER_SECRET Lost or Corrupted

### What it means

Every challenge flag is derived as:
```
infodays{ HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32] }
```
If the secret changes, all flags become invalid. Players cannot score.

### 2A — Secret still in K8s (cluster alive)

```bash
# Export current secret value
kubectl get secret ctfd-secrets -n ctfd \
  -o jsonpath='{.data.CTF_MASTER_SECRET}' | base64 -d
```

Save this value to `.env.local` and to a secure offline location immediately.

### 2B — Secret lost, cluster alive, .env.local intact

```bash
source .env.local  # loads CTF_MASTER_SECRET

# Re-inject into K8s (patch existing secret)
kubectl patch secret ctfd-secrets -n ctfd \
  --type='json' \
  -p="[{\"op\":\"replace\",\"path\":\"/data/CTF_MASTER_SECRET\",\"value\":\"$(echo -n "$CTF_MASTER_SECRET" | base64)\"}]"

# Restart pods to pick up new value
kubectl rollout restart deployment/ctfd -n ctfd
kubectl rollout restart deployment/controller-api -n ctfd
```

### 2C — Secret lost everywhere (cluster dead + .env.local gone)

**This is the worst case. Flags for all teams are unrecoverable.**

Recovery options (none are clean):
1. **Restore cluster from etcd** (DigitalOcean daily backup) — contact DO Support. Expect 30–60 min.
2. **Generate new secret** — re-derive all flags, re-import to CTFd. Teams that already submitted correct flags will have their submissions invalidated. Takes ~30 min.

If choosing option 2:
```bash
# Generate new secret
NEW_SECRET=$(openssl rand -hex 32)
echo "export CTF_MASTER_SECRET=$NEW_SECRET" > .env.local

# Re-import all flags
source .env.local
python3 controller/import_flags.py \
  --ctfd-url https://ctfd.infodays.net \
  --admin-token "$CTFD_ADMIN_TOKEN" \
  --master-secret "$CTF_MASTER_SECRET"
```

**Prevention**: Store `CTF_MASTER_SECRET` in at least 2 independent locations:
- `.env.local` on your machine
- Encrypted note in a password manager (1Password, Bitwarden)
- K8s Secret (backed up by etcd)

---

## Scenario 3 — DOKS Cluster Destroyed

Full cluster rebuild. Estimated time: **20–30 minutes**.

### 3A — Cluster exists but nodes are gone (node pool deleted)

```bash
# Re-provision node pool via Terraform
terraform -chdir=infra/terraform apply \
  -target=digitalocean_kubernetes_node_pool.workers \
  -auto-approve

# Kubeconfig may have expired — refresh
doctl kubernetes cluster kubeconfig save infodays-ctf

# Reapply all manifests (stateful data in PVCs survives node pool deletion)
kubectl apply -f k8s/ctfd/secrets.local.yaml
kubectl apply -f k8s/ctfd/
kubectl apply -f k8s/controller/
kubectl apply -f k8s/network-policies/
kubectl apply -f k8s/rbac/
```

**Expected RTO: 10–15 minutes.**

---

### 3B — Full cluster deleted (terraform destroy or accident)

```bash
# Step 1: Terraform 3-pass provisioning
terraform -chdir=infra/terraform init \
  -backend-config="access_key=$AWS_ACCESS_KEY_ID" \
  -backend-config="secret_key=$AWS_SECRET_ACCESS_KEY"

# Pass 1: cluster + registry
terraform -chdir=infra/terraform apply \
  -target=digitalocean_kubernetes_cluster.infodays \
  -target=digitalocean_container_registry.infodays \
  -auto-approve

# Pass 2: namespaces + helm (cert-manager + ingress-nginx)
doctl kubernetes cluster kubeconfig save infodays-ctf
terraform -chdir=infra/terraform apply \
  -target=kubernetes_namespace.cert_manager \
  -target=kubernetes_namespace.ctfd \
  -target=kubernetes_namespace.challenges \
  -target=kubernetes_namespace.ingress_nginx \
  -target=helm_release.ingress_nginx \
  -target=helm_release.cert_manager \
  -auto-approve

# Pass 3: everything else (DNS, network policies, RBAC)
terraform -chdir=infra/terraform apply -auto-approve

# Step 2: Apply K8s manifests
kubectl apply -f k8s/ctfd/secrets.local.yaml
kubectl apply -f k8s/ctfd/services.yaml
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml
kubectl apply -f k8s/ctfd/redis-deployment.yaml
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl apply -f k8s/ctfd/proxysql-deployment.yaml
kubectl apply -f k8s/ctfd/networkpolicy.yaml

# Wait for MySQL to be ready
kubectl rollout status statefulset/mysql -n ctfd --timeout=5m

# Step 3: Restore MySQL from latest Spaces backup
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  bash scripts/restore-mysql.sh --latest

# Step 4: Create plugin ConfigMaps
kubectl create configmap ctfd-plugin-init --from-file=__init__.py=ctfd-plugin/__init__.py -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ctfd-plugin-js --from-file=plugin.js=ctfd-plugin/assets/plugin.js -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ctfd-plugin-css --from-file=style.css=ctfd-plugin/assets/style.css -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ctfd-plugin-logo-dark --from-file=logo-dark.png=ctfd-plugin/assets/logo-dark.png -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ctfd-plugin-logo-light --from-file=logo-light.png=ctfd-plugin/assets/logo-light.png -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap challenge-manifests --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -

# Step 5: Deploy CTFd + ingress + controller
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl apply -f k8s/ctfd/ingress.yaml
kubectl apply -f k8s/ctfd/ingress-login-ratelimit.yaml
kubectl apply -f k8s/ctfd/nginx-global-config.yaml
kubectl apply -f k8s/ctfd/pdb.yaml
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml
kubectl apply -f k8s/controller/api-deployment.yaml
kubectl apply -f k8s/controller/daemon-deployment.yaml
kubectl apply -f k8s/challenges/resource-limits.yaml

# Step 6: MySQL replication
kubectl apply -f k8s/ctfd/mysql-replica-statefulset.yaml
bash scripts/setup-mysql-replication.sh

# Step 7: Backup CronJob
kubectl create secret generic spaces-backup-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/ctfd/backup-cronjob.yaml

# Step 8: Bulk spawn challenges + update TCP port map
kubectl rollout restart deployment/controller-api -n ctfd
kubectl rollout status deployment/controller-api -n ctfd --timeout=3m
kubectl exec -n ctfd deployment/controller-api -- \
  python3 /app/bulk_spawn.py \
  --ctfd-url https://ctfd.infodays.net \
  --admin-token "$CTFD_ADMIN_TOKEN"

# Step 9: Update DNS apex records (new node IPs after rebuild)
terraform -chdir=infra/terraform apply \
  -target=digitalocean_record.challenges_apex_a \
  -auto-approve

echo "Cluster restored. Verify at https://ctfd.infodays.net"
```

**Expected RTO: 25–35 minutes.**

---

## Scenario 4 — Terraform State Corrupted or Lost

### 4A — State file corrupted (JSON parse errors)

```bash
# Download current state
aws s3 cp s3://infodays-ctf-tfstate/cluster/terraform.tfstate ./terraform.tfstate.corrupted \
  --endpoint-url https://fra1.digitaloceanspaces.com

# Try to validate it
python3 -m json.tool terraform.tfstate.corrupted > /dev/null && echo "JSON valid" || echo "JSON broken"

# If corrupted, check if Spaces has a previous version
aws s3api list-object-versions \
  --bucket infodays-ctf-tfstate \
  --prefix cluster/terraform.tfstate \
  --endpoint-url https://fra1.digitaloceanspaces.com \
  | python3 -m json.tool | grep -A5 "VersionId\|LastModified"
```

### 4B — State lost entirely

```bash
# Import existing infrastructure back into state manually
# This is slow but recoverable. Import the most critical resources first:

CLUSTER_ID=$(doctl kubernetes cluster list --no-header --format ID | head -1)
terraform -chdir=infra/terraform import \
  digitalocean_kubernetes_cluster.infodays "$CLUSTER_ID"

# For each resource: find its DO/K8s ID and terraform import it
# See: https://registry.terraform.io/providers/digitalocean/digitalocean/latest/docs
```

**Prevention**: Enable versioning on the Spaces bucket (one-time):
```bash
aws s3api put-bucket-versioning \
  --bucket infodays-ctf-tfstate \
  --versioning-configuration Status=Enabled \
  --endpoint-url https://fra1.digitaloceanspaces.com
```

**Expected RTO: 30–60 minutes** (contact DO Support if versioning not enabled and state is gone).

---

## Scenario 5 — nginx Ingress Down (HTTPS unreachable)

```bash
# Check
kubectl get pods -n ingress-nginx
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=30

# Restart ingress controller
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=2m

# If pod stuck — check for resource pressure
kubectl describe pod -n ingress-nginx -l app.kubernetes.io/component=controller | tail -20
```

**Expected RTO: 1–2 minutes (auto-restart usually handles it).**

---

## Scenario 6 — TLS Certificate Expired

```bash
# Check certificate status
kubectl get certificate -n ctfd
kubectl get certificate -n ingress-nginx
kubectl describe certificate ctfd-tls -n ctfd | grep -A5 "Status\|Reason\|Message"

# Force renewal
kubectl cert-manager renew ctfd-tls -n ctfd
kubectl cert-manager renew challenges-tls -n ctfd  # if using TLS for challenges

# Check cert-manager is healthy
kubectl get pods -n cert-manager
kubectl logs -n cert-manager deployment/cert-manager --tail=50 | grep -i "error\|renew\|order"

# Nuclear option: delete the certificate and let cert-manager recreate it
kubectl delete certificate ctfd-tls -n ctfd
kubectl apply -f infra/terraform/  # or reapply the cert resource

# Verify DO DNS token is present (required for DNS-01)
kubectl get secret do-dns-token -n cert-manager
```

**Expected RTO: 5 minutes** (cert issuance takes ~2 min via DNS-01).

---

## Scenario 7 — Challenge Ports Unreachable (NodePort)

Players can't connect to `challenges.infodays.net:<port>`.

```bash
# 1. Check NetworkPolicy
kubectl get networkpolicy allow-nodeport-to-challenges -n challenges -o yaml \
  | grep -A10 "ports:"
# Must include: 8080, 1337, 4444

# 2. Check DO firewall allows NodePort range
doctl compute firewall list
# Look for rule: protocol:tcp, ports:30000-32767, address:0.0.0.0/0

# 3. Check DNS apex A records point to current worker node IPs
dig challenges.infodays.net A +short
kubectl get nodes -o wide | grep -v control-plane | awk '{print $7}'
# IPs should match

# 4. Fix stale DNS after autoscale
terraform -chdir=infra/terraform apply \
  -target=digitalocean_record.challenges_apex_a \
  -auto-approve
```

**Expected RTO: 5–10 minutes** (mostly DNS TTL propagation).

---

## Scenario 8 — Admin Panel Locked Out

```bash
# Reset admin password via direct MySQL access
PASS=$(kubectl get secret ctfd-secrets -n ctfd \
  -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)

# Generate bcrypt hash for new password (requires python3 + bcrypt)
NEW_HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'NewAdminPass123!', bcrypt.gensalt()).decode())")

# Update in MySQL
kubectl exec mysql-0 -n ctfd -- \
  mysql -u root -p"$PASS" ctfd \
  -e "UPDATE users SET password='${NEW_HASH}' WHERE name='admin';"

# Flush Redis (clear any cached auth state)
kubectl exec -n ctfd redis-0 -- redis-cli FLUSHDB
```

---

## Pre-Event Backup Checklist

Run through this **before opening the event**:

```bash
# 1. Take a tagged pre-event backup
PASS=$(kubectl get secret ctfd-secrets -n ctfd \
  -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)
MYSQL_POD=$(kubectl get pod -n ctfd -l app=mysql -o jsonpath='{.items[0].metadata.name}')
OUTFILE="backups/ctfd-pre-event-$(date -u +%Y-%m-%dT%H-%M-%SZ).sql.gz"
kubectl exec "$MYSQL_POD" -n ctfd -- \
  mysqldump -u root -p"$PASS" --single-transaction --set-gtid-purged=OFF ctfd \
  | gzip -9 > "$OUTFILE"

# Upload with pre-event tag (protected from rotation)
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  aws s3 cp "$OUTFILE" \
  "s3://infodays-ctf-tfstate/backups/$(basename $OUTFILE)" \
  --endpoint-url https://fra1.digitaloceanspaces.com

# 2. Verify CronJob is scheduled
kubectl get cronjob mysql-backup -n ctfd
# Expected: SCHEDULE=*/30 * * * *, ACTIVE=0, LAST SCHEDULE=<recent>

# 3. Verify CTF_MASTER_SECRET is accessible
kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.CTF_MASTER_SECRET}' \
  | base64 -d | wc -c
# Expected: 64 (32 bytes hex-encoded)

# 4. Verify MySQL replica is in sync
kubectl exec mysql-0 -n ctfd -- \
  mysql -u root -p"$PASS" -e "SHOW MASTER STATUS\G" 2>/dev/null

kubectl exec mysql-replica-0 -n ctfd -- \
  mysql -u root -p"$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)" \
  -e "SHOW REPLICA STATUS\G" 2>/dev/null \
  | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind"
# Expected: both YES, Seconds_Behind_Source=0
```

---

## Post-Event Backup

Run immediately when the event closes:

```bash
# Final backup — tagged to prevent rotation
PASS=$(kubectl get secret ctfd-secrets -n ctfd \
  -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)
MYSQL_POD=$(kubectl get pod -n ctfd -l app=mysql -o jsonpath='{.items[0].metadata.name}')
OUTFILE="backups/ctfd-event-final-$(date -u +%Y-%m-%dT%H-%M-%SZ).sql.gz"

kubectl exec "$MYSQL_POD" -n ctfd -- \
  mysqldump -u root -p"$PASS" \
  --single-transaction --set-gtid-purged=OFF \
  --all-databases ctfd \
  | gzip -9 > "$OUTFILE"

# Upload and keep forever
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  aws s3 cp "$OUTFILE" \
  "s3://infodays-ctf-tfstate/backups/$(basename $OUTFILE)" \
  --endpoint-url https://fra1.digitaloceanspaces.com

echo "Final backup: $OUTFILE"
echo "Verify with: bash scripts/restore-mysql.sh --list"
```

---

## Quick Reference — Useful Commands

```bash
# Cluster health
kubectl get nodes
kubectl get pods -A | grep -v Running | grep -v Completed

# Recent events (errors)
kubectl get events -A --sort-by=.lastTimestamp | tail -20

# MySQL health
kubectl exec mysql-0 -n ctfd -- mysqladmin status -u root -p"$PASS"

# Redis health
kubectl exec redis-0 -n ctfd -- redis-cli INFO server | grep redis_version

# CronJob last run
kubectl get jobs -n ctfd --sort-by=.metadata.creationTimestamp | tail -5

# Certificate expiry
kubectl get certificate -A -o custom-columns='NAME:.metadata.name,EXPIRY:.status.notAfter,READY:.status.conditions[0].status'

# Check backup list
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
  bash scripts/restore-mysql.sh --list
```
