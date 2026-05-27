# InfoDays CTF — Event-Day Runbook

**Event**: InfoDays CTF | **Domain**: ctfd.infodays.net | **Duration**: 12 hours
**Audience**: Operations team only — keep this runbook open throughout the event.

---

## Before Opening

### 1. Verify all systems are green

Run through `docs/pre-event-checklist.md` in its entirety. Do not proceed until all items are checked.

### 2. Open the event in CTFd

Option A — via the CTFd admin panel:
- Go to `https://ctfd.infodays.net/admin/config`
- Set the event start time to now (or click **Start** if using manual mode)

Option B — via curl:
```bash
curl -X PATCH https://ctfd.infodays.net/api/v1/configs \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start": "'"$(date -u +%Y-%m-%dT%H:%M:%S)"'"}'
```

Announce to teams that the event is open.

---

## During Event — Common Operations

### Live health watch

Keep these checks running in separate terminals during the first 30 minutes and any peak period:

```bash
watch -n 30 'kubectl top nodes && kubectl get pods -A | egrep "CrashLoopBackOff|Error|OOMKilled|Pending|0/" || true'
watch -n 60 'kubectl get events -A --sort-by=.lastTimestamp | tail -40'
kubectl logs -n monitoring -l app=alloy-node --tail=100 -f
```

Escalate if any node stays above 80% memory, if any platform pod restarts, or if MySQL/ProxySQL reports connection errors.

### Add a new challenge mid-event

**Recommended**: Use the one-command deploy script:

```bash
bash scripts/deploy-challenge.sh challenges/manifests/<challenge-id>.yaml
```

This handles everything automatically — CTFd entry, ConfigMap, controller restart, bulk_spawn (service) or flag import (static).

**Manual steps** (if the script can't be used):

```bash
# Service challenges (type: http/tcp):
# 1. Build and push the new challenge image
bash scripts/push-challenge.sh <challenge-id> challenges/base-images/<type> <type>

# 2. Add the challenge manifest to challenges/manifests/<challenge-id>.yaml

# 3. Update the ConfigMap and restart the controller
kubectl create configmap challenge-manifests \
  --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/controller-api -n ctfd

# 4. Re-run provisioning via the on-demand provisioner pod
bash scripts/deploy-challenge.sh challenges/manifests/<challenge-id>.yaml

# Static challenges (type: static):
# 1. Add the manifest to challenges/manifests/<challenge-id>.yaml
# 2. Update ConfigMap + restart controller (same as above)
# 3. Run import_flags to create the team flag row:
kubectl scale deployment/controller-provisioner -n ctfd --replicas=1
kubectl rollout status deployment/controller-provisioner -n ctfd --timeout=120s
PROVISIONER_POD="$(kubectl get pods -n ctfd -l app=controller-provisioner --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
kubectl exec -n ctfd "$PROVISIONER_POD" -- \
  env CTFD_ADMIN_TOKEN="$CTFD_ADMIN_TOKEN" \
  python3 import_flags.py --ctfd-url https://ctfd.infodays.net
kubectl scale deployment/controller-provisioner -n ctfd --replicas=0
# No bulk_spawn needed — plugin serves per-team zips on the fly via /download/{id}
```

### Restart a broken team pod (manual)

```bash
kubectl rollout restart deployment/team-{id}-{challenge-id} -n challenges
```

Replace `{id}` with the numeric team ID and `{challenge-id}` with the challenge ID (e.g., `team-3-web-sqli`).

### Check for cheating (cross-team flag submission)

The platform cryptographically prevents cross-team flag acceptance, but logs all attempts to a
`cheaters` table for post-event review.

```bash
curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  https://ctfd.infodays.net/admin/cheaters | jq .
```

Fields returned: `submitting_team`, `submitting_team_id`, `submitting_user`, `submitting_user_id`,
`submitted_flag`, `owner_team`, `owner_team_id`, `challenge`, `submitted_at`.

An entry here means the team submitted a flag that was cryptographically matched to another team.
The submission was **rejected** (returned False). Log this for integrity review after the event.

### Force-suspend a team's pod (admin action)

```bash
kubectl patch deployment/team-{id}-{challenge-id} -n challenges \
  -p '{"spec":{"replicas":0}}'
```

Use this to suspend a team that is abusing the infrastructure.

### Scale CTFd under unexpected load

Current baseline is 5 replicas with 4 workers each. Scale up if needed:
```bash
kubectl scale deployment/ctfd -n ctfd --replicas=8
```

Scale back down after load subsides:
```bash
kubectl scale deployment/ctfd -n ctfd --replicas=5
```

### Scale controller API under activate/status pressure

Current baseline is 4 replicas. If activate or status calls are failing or slow and node memory has headroom:
```bash
kubectl scale deployment/controller-api -n ctfd --replicas=6
```

Scale back to 4 once the burst ends. Avoid returning to the old 8+ replica profile unless Metrics Server shows clear memory headroom.

### Flush Redis sessions (emergency — forces all users to re-login)

Use this only if you changed `SESSION_COOKIE_DOMAIN` or suspect corrupted session state causing login loops:
```bash
kubectl exec -n ctfd redis-0 -- redis-cli FLUSHDB
```

**Warning:** This invalidates all active sessions. Every logged-in team member will be logged out and must re-login. Avoid during peak competition hours.

### Extend the event end time

CTFd admin panel → **Configuration** → **End time** → update and save.

---

## Disaster Recovery

### MySQL OOM or crash

MySQL should run on the dedicated `mysql-pool` node. If it OOM-kills or crashes, symptoms include CTFd 500 errors, ProxySQL backend errors, or `CrashLoopBackOff`.

```bash
# Check MySQL status
kubectl get pods -n ctfd -l app=mysql

# If OOM-killed (exit code 137), it should auto-restart. If stuck:
kubectl delete pod mysql-0 -n ctfd
# StatefulSet will recreate with PVC data intact

# If data is corrupted, restore from backup:
kubectl exec -i mysql-0 -n ctfd -- mysql -u root -p"$MYSQL_ROOT_PASSWORD" ctfd < backups/ctfd-backup-LATEST.sql
```

### Full cluster restore procedure

If the cluster was destroyed and needs to be rebuilt:

```bash
# 1. Terraform 3-pass provisioning (see CLAUDE.md for full commands)
terraform -chdir=infra/terraform apply -target=digitalocean_kubernetes_cluster.infodays -target=digitalocean_container_registry.infodays -auto-approve
doctl kubernetes cluster kubeconfig save infodays-ctf
terraform -chdir=infra/terraform apply -target=kubernetes_namespace.cert_manager -target=kubernetes_namespace.ctfd -target=kubernetes_namespace.challenges -target=kubernetes_namespace.monitoring -target=kubernetes_namespace.ingress_nginx -target=helm_release.ingress_nginx -target=helm_release.cert_manager -auto-approve
terraform -chdir=infra/terraform apply -auto-approve

# 2. Deploy core CTFd stack — secrets and services first, then stateful components
kubectl apply -f k8s/ctfd/secrets.local.yaml
kubectl apply -f k8s/ctfd/services.yaml
kubectl apply -f k8s/monitoring/metrics-server.yaml
kubectl apply -f k8s/ctfd/mysql-statefulset.yaml
kubectl apply -f k8s/ctfd/redis-deployment.yaml       # StatefulSet with 1Gi PVC + AOF
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl apply -f k8s/ctfd/proxysql-deployment.yaml
kubectl apply -f k8s/ctfd/networkpolicy.yaml

# Wait for MySQL primary to be ready before continuing
kubectl rollout status statefulset/mysql -n ctfd

# 3. Create ConfigMaps from plugin files
kubectl create configmap ctfd-plugin-init --from-file=__init__.py=ctfd-plugin/__init__.py -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap ctfd-plugin-js --from-file=plugin.js=ctfd-plugin/assets/plugin.js -n ctfd --dry-run=client -o yaml | kubectl apply -f -

# 4. Deploy CTFd + ingress
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl apply -f k8s/ctfd/ingress.yaml

# 5. Restore MySQL backup to primary
kubectl cp backups/ctfd-backup-LATEST.sql ctfd/mysql-0:/tmp/restore.sql
kubectl exec -i mysql-0 -n ctfd -- bash -c 'echo "SET FOREIGN_KEY_CHECKS=0;" | cat - /tmp/restore.sql | mysql -u root -p"$MYSQL_ROOT_PASSWORD" ctfd'

# 6. Deploy MySQL replica for recovery and configure GTID replication.
# Do not enable ProxySQL read splitting during the event unless a fresh soak test passes.
kubectl apply -f k8s/ctfd/mysql-replica-statefulset.yaml
kubectl rollout status statefulset/mysql-replica -n ctfd
bash scripts/setup-mysql-replication.sh
# This script: creates repl user on primary (mysql_native_password), seeds replica from primary dump,
# configures CHANGE REPLICATION SOURCE TO, enables super_read_only on replica, creates ctfd user on replica.

# 7. Deploy controller (create secret with correct key name)
kubectl create secret generic controller-key --from-literal=CONTROLLER_KEY=<key> -n ctfd
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml
kubectl apply -f k8s/controller/api-deployment.yaml   # 4 replicas, 250m CPU request
kubectl apply -f k8s/controller/daemon-deployment.yaml

# 8. Apply CiliumNetworkPolicy for controller → kube-apiserver access
# (required on DOKS — standard NetworkPolicy cannot target kube-apiserver)

# 9. Pre-create challenge manifests ConfigMap, bulk spawn, import flags
kubectl create configmap challenge-manifests --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/controller-api -n ctfd
# Run bulk_spawn and import_flags via controller-provisioner, not controller-api
```

**Notes on Redis after restore:**
- Redis data is persisted via AOF to a 1Gi PVC (`redis-data-redis-0`). If the PVC survived the restore (cluster recreated but PVC kept), sessions are preserved.
- If the PVC is fresh/empty, all sessions are cleared — teams must re-login. This is expected.
- If you see login loops after changing `SESSION_COOKIE_DOMAIN`, run `kubectl exec -n ctfd redis-0 -- redis-cli FLUSHDB` to clear conflicting old-domain cookies.

### Admin password reset

If admin credentials are lost (e.g., after restoring from an old backup):

```bash
kubectl exec -it deployment/ctfd -n ctfd -- python3 -c "
from CTFd.models import Users, db
from CTFd import create_app
app = create_app()
with app.app_context():
    admin = Users.query.filter_by(type='admin').first()
    admin.password = 'NewPassword123!'
    db.session.commit()
    print(f'Reset password for: {admin.name}')
"
```

---

## End of Event

### 1. Freeze the scoreboard

Option A — via the CTFd admin panel: click **Freeze Scores**.

Option B — via curl:
```bash
curl -X PATCH https://ctfd.infodays.net/api/v1/configs \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"freeze": "'"$(date -u +%Y-%m-%dT%H:%M:%S)"'"}'
```

### 2. Announce winners

Read the top teams from the scoreboard: `https://ctfd.infodays.net/scoreboard`

### 3. Export scores to CSV

CTFd Admin → **Export** → download CSV.

Alternatively:
```bash
curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  https://ctfd.infodays.net/api/v1/scoreboard/top/50 | jq . > scores-final.json
```

### 4. Take final MySQL backup

```bash
bash scripts/backup-mysql.sh
```

Verify the backup file exists and is non-empty before proceeding to teardown.

---

## Teardown

### Destroy all challenge pods (keep CTFd running)

This deletes all pods, services, secrets, and ingresses managed by the controller. CTFd, MySQL, Redis, and the controller itself remain running.

```bash
kubectl delete deployments,services,secrets,ingresses \
  -l managed-by=ctf-controller -n challenges
```

### Full infrastructure teardown

> **⚠️ WARNING — IRREVERSIBLE ACTION**
>
> `terraform destroy` permanently destroys the DOKS cluster, node pool, load balancer,
> DOCR registry, and all DNS records. **This cannot be undone.**
>
> Before running:
> - Confirm the final MySQL backup is saved locally (`ls -lh backups/`)
> - Confirm scores are exported
> - Confirm all team members agree to proceed
> - This is NOT reversible — confirm team decision first

```bash
cd infra/terraform
terraform destroy
```

Type `yes` when prompted. The destroy takes 5–15 minutes.
