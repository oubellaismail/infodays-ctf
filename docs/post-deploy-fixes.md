# Post-Deploy Fixes — 2026-04-03

Bugs found and resolved after initial cluster provisioning and bulk_spawn.

---

## Fix 1 — Controller RBAC missing `get` on Services

**Symptom:** All TCP challenges showed "Running" but no `nc` link. Controller logs showed:
```
Failed to build TCP URL for team-1-misc-riddle-svc: 403 Forbidden
```

**Root cause:** The wrong RBAC manifest was applied (`k8s/controller/rbac.yaml` instead of `k8s/rbac/challenge-controller-rbac.yaml`). The old file only had `create` on Services — `get` was missing, so `build_challenge_url` in `api.py` failed every time it tried to read the NodePort.

**Fix:** Apply the correct manifest:
```bash
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml
```

RBAC changes take effect immediately — no pod restart needed.

---

## Fix 2 — Plugin SERVICE_CATEGORIES missing 4 categories

**Symptom:** crypto, forensics, reversing, and osint challenges showed only the description — no Start Instance button, no UI at all.

**Root cause:** `ctfd-plugin/assets/plugin.js` line 26 had:
```js
var SERVICE_CATEGORIES = ["web", "pwn", "misc"];
```
The plugin skipped any challenge category not in that list.

**Fix:** Extended to all 7 categories:
```js
var SERVICE_CATEGORIES = ["web", "pwn", "misc", "crypto", "forensics", "reversing", "osint"];
```

---

## Fix 3 — TCP challenge URL rendered as broken link

**Symptom:** misc and pwn challenges showed "Running" + Stop button but no connection info (even after Fix 1 was applied).

**Root cause:** For TCP challenges, `api.py` returns `"nc challenges.infodays.net <port>"`. The plugin rendered this as an `<a href>` anchor, which browsers treat as a relative path — invisible or broken.

**Fix:** Detect `nc ` prefix and render as a `<code>` block instead:
```js
if (challenge.url.startsWith("nc ")) {
  var code = document.createElement("code");
  code.textContent = challenge.url;
  code.style.cssText = "... user-select:all; cursor:text;";
  container.appendChild(code);
} else {
  // HTTP challenge: clickable link
  var urlLink = document.createElement("a");
  ...
}
```

---

## Fix 4 — CTFd challenge names mismatched manifest IDs

**Symptom:** Clicking Start on Digital Origins, Encoded Message, Hidden in Plain Sight, or The Gatekeeper triggered `POST /controller-proxy/activate 404 Not Found`.

**Root cause:** The plugin derives the `challenge_id` sent to the controller by slugifying the CTFd challenge name:
```js
info.name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")
```
The 4 new challenges had human-friendly names that didn't match their manifest IDs:

| CTFd name | Derived slug | Manifest ID |
|---|---|---|
| Digital Origins | `digital-origins` | `osint-origins` |
| Encoded Message | `encoded-message` | `crypto-b64` |
| Hidden in Plain Sight | `hidden-in-plain-sight` | `forensics-hidden` |
| The Gatekeeper | `the-gatekeeper` | `reversing-gatekeeper` |

The controller looks up K8s resources by manifest ID, so it found nothing and returned 404.

**Fix:** Renamed the 4 CTFd challenges via admin API to names that slugify to the manifest ID, and updated the manifest `name` fields to match:

| New CTFd name | Derived slug | Manifest ID |
|---|---|---|
| Crypto B64 | `crypto-b64` ✓ | `crypto-b64` |
| Forensics Hidden | `forensics-hidden` ✓ | `forensics-hidden` |
| Reversing Gatekeeper | `reversing-gatekeeper` ✓ | `reversing-gatekeeper` |
| Osint Origins | `osint-origins` ✓ | `osint-origins` |

**Convention going forward:** CTFd challenge name must slugify to its manifest `id`. Keep names in the format `<Category> <Descriptor>` (e.g., "Pwn BoF", "Web SQLi").

---

## Fix 5 — `challenges.infodays.net` had no apex A record

**Symptom:** Even after Fix 1 and Fix 3, the `nc` command had no hostname to resolve — `dig challenges.infodays.net` returned nothing.

**Root cause:** Terraform `dns.tf` only had a wildcard `*.challenges.infodays.net` record pointing to the NGINX LB IP (used for HTTP challenges via ingress). TCP challenges use `nc challenges.infodays.net <nodeport>` which needs the apex (`@`) to resolve to node IPs, since NodePort traffic goes directly to cluster nodes — not through the LB.

The DO LB has a forwarding rule limit (~10 rules) and only exposes ports 80 and 443, so TCP ports cannot be routed through it.

**Fix:** Added apex A records dynamically via Terraform using `digitalocean_droplets` data source filtered by DOKS cluster tag — no hardcoded IPs:

```hcl
data "digitalocean_droplets" "workers" {
  filter {
    key    = "tags"
    values = ["k8s:${digitalocean_kubernetes_cluster.infodays.id}"]
    all    = false
  }
}

resource "digitalocean_record" "challenges_apex_a" {
  count  = length(data.digitalocean_droplets.workers.droplets)
  domain = digitalocean_domain.challenges.name
  type   = "A"
  name   = "@"
  value  = data.digitalocean_droplets.workers.droplets[count.index].ipv4_address
  ttl    = 60
}
```

If nodes are replaced (upgrade, resize), run `terraform apply` to refresh the records.

---

## Fix 6 — 4 challenges missing from CTFd (import_flags skipped them)

**Symptom:** `import_flags.py` logged `WARNING Challenge not found in CTFd` for crypto, forensics, reversing, and osint challenges.

**Root cause:** The 4 new challenges were never created in CTFd — only the original 3 (web, pwn, misc) existed. `import_flags.py` matches challenges by CTFd name; unmatched ones are skipped.

**Fix:** Created the 4 missing challenges via the CTFd admin API, then re-ran `import_flags.py`. Result: 4 team-bound flag rows created, 3 skipped (already existed).

---

## Fix 7 — Controller category filter only covered 3 of 7 challenges

**Symptom:** `bulk_spawn.py` and `import_flags.py` only processed web, pwn, and misc challenges — the 4 new categories were ignored.

**Root cause:** Both scripts had a hardcoded category filter:
```python
challenges = [c for c in load_manifests() if c["category"] in {"web", "pwn", "misc"}]
```

**Fix:** Extended to all 7 categories in both files:
```python
challenges = [c for c in load_manifests() if c["category"] in {
    "web", "pwn", "misc", "crypto", "forensics", "reversing", "osint"
}]
```

---

## Fix 8 — DO firewall blocking NodePort range

**Symptom:** `nc challenges.infodays.net <port>` timed out — connection refused even after DNS resolved.

**Root cause:** The DOKS worker firewall (`k8s-*-worker`) only allows inbound from private RFC-1918 ranges. The NodePort range 30000-32767 was not open to the public internet.

**Fix:**
```bash
doctl compute firewall add-rules <worker-firewall-id> \
  --inbound-rules "protocol:tcp,ports:30000-32767,address:0.0.0.0/0"
```

---

## Fix 9 — NetworkPolicy blocking NodePort ingress to challenge pods

**Symptom:** TCP connections reached the node but were dropped before hitting the pod.

**Root cause:** `allow-ingress-to-challenges` NetworkPolicy only permitted traffic from the `ingress-nginx` namespace. NodePort traffic enters pods from kube-proxy/Cilium at the host level — not from a namespace — so `default-deny-all` dropped it.

**Fix:** Added a separate NetworkPolicy allowing ingress on TCP challenge ports from any source:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nodeport-to-challenges
  namespace: challenges
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - ports:
    - port: 1337
      protocol: TCP
    - port: 4444
      protocol: TCP
```

Port 8080 (HTTP challenges) is intentionally excluded — those go through NGINX ingress only.

---

## Fix 10 — CTF_MASTER_SECRET missing from CTFd pods

**Symptom:** Flag submissions always returned "Incorrect" even with the correct derived flag.

**Root cause:** The custom `team` flag type plugin (`__init__.py`) calls `os.environ.get("CTF_MASTER_SECRET", "")` inside the CTFd process. The secret was present in the `ctfd-secrets` K8s Secret and mounted into the controller pods — but **not** into the CTFd deployment. The plugin silently returned `False` on every validation attempt.

**Fix:** Added `CTF_MASTER_SECRET` to the CTFd deployment env vars in `k8s/ctfd/deployment.yaml`:
```yaml
- name: CTF_MASTER_SECRET
  valueFrom:
    secretKeyRef:
      name: ctfd-secrets
      key: CTF_MASTER_SECRET
```

**Prevention:** Added a check to `docs/pre-event-checklist.md` under CTFd Platform:
```bash
kubectl exec -n ctfd deployment/ctfd -- env | grep CTF_MASTER_SECRET
```

---

## Phase 7 Scaling — MySQL Read Replica, Redis Caching, Node Autoscaler

### MySQL Read Replica + ProxySQL Read/Write Splitting

**Problem:** `/challenges` page p50=7.4s at 200 VUs. All queries (reads + writes) go to a single MySQL pod. With 200 VUs, all 5 CTFd replicas × 4 gevent workers queue on the same MySQL connection pool.

**Solution:**
1. MySQL primary gets GTID binlog enabled (`--gtid-mode=ON --log-bin`)
2. New `mysql-replica` StatefulSet (read-only, super-read-only)
3. ProxySQL query rules route `SELECT` → replica (hostgroup 1), writes → primary (hostgroup 0)
4. `SELECT ... FOR UPDATE` still goes to primary (write-intent reads)
5. ProxySQL `mysql_replication_hostgroups` auto-shuns a lagging replica

**Observed:** 45-min 200-VU test: ProxySQL routed 380K reads to replica (78%) and 103K writes to primary (22%), 0 ConnERR. Replication lag held at 0s throughout.

### CTFd Redis Page Caching

**Problem:** CTFd uses Redis for sessions only. Challenge list, solve counts, and scoreboard are re-queried from MySQL on every request — 50 identical DB queries when 50 teams refresh simultaneously.

**Solution:** Added `CACHE_TYPE=redis` and `CACHE_REDIS_URL=redis://redis:6379` to CTFd deployment. CTFd now caches challenge lists, solve counts, and scoreboard in Redis with configurable TTL. First request hits MySQL, subsequent requests served from Redis in ~5ms.

**Observed:** Redis caching confirmed active (`CACHE_TYPE=redis`). Challenge list and scoreboard API responses served from Redis after first hit.

### Node Pool Autoscaler

**Problem:** Fixed 5-node pool has no headroom for surprise attendance or node failure.

**Solution:** Changed Terraform from `node_count=5` to `auto_scale=true, min_nodes=3, max_nodes=8`. DOKS provisions new nodes when pods can't be scheduled, scales back during idle.

**Observed:** Terraform applied autoscaler (`auto_scale=true, min=3, max=8`). DOKS will provision new nodes automatically if pod scheduling pressure exceeds current capacity.

### Load Test Results (post Phase 7 scaling)

| Run | VUs | p50 | p95 | Error rate | Notes |
|-----|-----|-----|-----|------------|-------|
| Pre-scaling (run 4) | 200 | 2.87s | 8.77s | 0.04% | Status cache, CTFd probes fixed |
| Post-scaling (run 5) | 200 | 3.97s | 11.57s | 0.01% ✓ | Replica + Redis + autoscaler |

**p95 note:** p95 rose due to 62 login failures (24%) during the 50s VU ramp — new pods were still initialising when the test started. Subsequent iterations had no errors. The `activate` endpoint is the dominant p95 contributor (K8s API roundtrip is inherently ~1-3s). Error rate is now ≤0.01% which meets the <1% threshold.

**ProxySQL query distribution (run 5):** 380K reads → replica, 103K writes → primary; 0 ConnERR.

---

## Deployment checklist (apply after future fixes)

```bash
# 1. Update plugin.js ConfigMap and restart CTFd
kubectl create configmap ctfd-plugin-js \
  --from-file=plugin.js=ctfd-plugin/assets/plugin.js \
  -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/ctfd -n ctfd

# 2. Update challenge manifests ConfigMap and restart controller
kubectl create configmap challenge-manifests \
  --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/controller-api -n ctfd

# 3. Apply RBAC changes (take effect immediately)
kubectl apply -f k8s/rbac/challenge-controller-rbac.yaml

# 4. Refresh DNS apex records after node changes
terraform -chdir=infra/terraform apply -target=digitalocean_record.challenges_apex_a -auto-approve

# 5. Deploy MySQL replica + replication
kubectl apply -f k8s/ctfd/mysql-replica-statefulset.yaml
bash scripts/setup-mysql-replication.sh

# 6. Apply ProxySQL read/write splitting config
kubectl apply -f k8s/ctfd/proxysql-configmap.yaml
kubectl rollout restart deployment/proxysql -n ctfd

# 7. Enable Redis caching in CTFd
kubectl apply -f k8s/ctfd/deployment.yaml
kubectl rollout restart deployment/ctfd -n ctfd

# 8. Enable node autoscaler (via Terraform)
terraform -chdir=infra/terraform apply -auto-approve
```
