# InfoDays CTF — Pre-Event Checklist

**Event**: InfoDays CTF | **Domain**: ctfd.infodays.net | **Target**: 60 users / ~15 teams / 12 hours
**Instructions**: Work through each section top-to-bottom. Check off each item as it passes.
Do NOT open the event until every item in the Ops Readiness section is checked.

---

## Infrastructure

- [ ] DOKS: 4 general workers plus 1 dedicated MySQL node Ready
  `kubectl get nodes`
  Expected: 5 nodes total, all STATUS=Ready
  Check autoscaler: `doctl kubernetes cluster node-pool get infodays-ctf infodays-workers --format AutoScale,MinNodes,MaxNodes,Count`
  Expected: AutoScale=true, MinNodes=4, MaxNodes=4
  Check MySQL pool: `doctl kubernetes cluster node-pool list infodays-ctf --format Name,Size,Count,Labels`
  Expected: `mysql-pool`, size `s-4vcpu-8gb`, Count=1, label `role=mysql`

- [ ] Metrics Server installed and usable
  `kubectl top nodes && kubectl top pods -A --containers | head`
  Expected: CPU and memory usage returned, not `Metrics API not available`

- [ ] DO Load Balancer: IP assigned and DNS resolving
  `kubectl get svc -n ingress-nginx`
  Then: `nslookup ctfd.infodays.net`
  Expected: IP returned matches Load Balancer external IP

- [ ] TLS certificate: valid and not expiring within 30 days
  `kubectl get certificate -n ctfd`
  Expected: READY=True; check EXPIRY is >30 days away

- [ ] DOCR: all challenge images present
  `doctl registry repository list-tags infodays-registry`
  Expected: all challenge image tags listed

---

## CTFd Platform

- [ ] CTF_MASTER_SECRET is set in CTFd pods (required for flag validation)
  `kubectl exec -n ctfd deployment/ctfd -- env | grep CTF_MASTER_SECRET`
  Expected: `CTF_MASTER_SECRET=<value>` — if missing, apply the deployment manifest:
  `kubectl apply -f k8s/ctfd/deployment.yaml && kubectl rollout restart deployment/ctfd -n ctfd`

- [ ] CTFd loads over HTTPS with valid TLS
  Open `https://ctfd.infodays.net` in a browser
  Expected: page loads, browser shows valid padlock

- [ ] Admin login works
  Log in at `https://ctfd.infodays.net/login` with admin credentials
  Expected: redirected to admin dashboard

- [ ] All team accounts created (import-teams.py ran successfully)
  `curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" https://ctfd.infodays.net/api/v1/teams | jq '.data | length'`
  Expected: count matches the number of teams imported from CSV

- [ ] CTFd settings correct: team mode on, registration disabled, event times set, flag format `infodays{...}` configured
  CTFd Admin → Configuration → verify each setting

- [ ] Scoreboard is visible (not frozen)
  `curl -s https://ctfd.infodays.net/api/v1/scoreboard/top/10 | jq .`
  Expected: JSON response with team scores (empty at start is fine)

- [ ] CTFd and controller baselines match the event-safe profile
  `kubectl get deploy -n ctfd ctfd controller-api proxysql`
  Expected: CTFd 5/5, controller-api 4/4, ProxySQL 2/2

- [ ] MySQL primary is isolated on the dedicated node pool
  `kubectl get pod mysql-0 -n ctfd -o wide`
  Expected: node name belongs to `mysql-pool`
  `kubectl describe node $(kubectl get pod mysql-0 -n ctfd -o jsonpath='{.spec.nodeName}') | grep -E "doks.digitalocean.com/node-pool|Allocated resources" -A8`
  Expected: MySQL node is not carrying CTFd, controller, ingress, or challenge workloads

---

## Challenge Infrastructure

- [ ] bulk_spawn.py ran successfully — all challenge pods exist in challenges namespace
  `kubectl get deployments -n challenges --no-headers | wc -l`
  Expected: count matches (teams × challenges) total

- [ ] import_flags.py ran — one `team` flag row per challenge (service + static) in CTFd
  `curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" -H "Content-Type: application/json" https://ctfd.infodays.net/api/v1/flags | jq '[.data[] | select(.type=="team")] | length'`
  Expected: count equals total number of challenges (service + static, e.g., 4 for web-sqli, pwn-bof, misc-riddle, misc-welcome)
  Note: type is `team` (not `static`) — one row covers all teams via HMAC derivation. Static challenges also use `team` type for per-team flag derivation.

- [ ] Static challenge download endpoint works
  Log in as any team member, visit `https://ctfd.infodays.net/download/misc-welcome`
  Expected: browser downloads `misc-welcome.zip` containing `flag.txt` with a team-specific flag
  Verify: download as two different teams → `flag.txt` contents differ (per-team HMAC)

- [ ] Sample end-to-end test: activate one Web, one Pwn, one Misc instance for team-999
  `curl -X POST http://controller-api.ctfd.svc.cluster.local:80/activate -H "X-Controller-Key: $CONTROLLER_KEY" -d '{"team_id":999,"challenge_id":"test-web-1"}'`
  (run from inside the cluster or use kubectl port-forward first)

- [ ] Verify FLAG env var inside test pod matches CTFd stored flag
  `kubectl exec -n challenges deployment/team-999-test-web-1 -- printenv FLAG`
  Compare output with the flag stored in CTFd for challenge test-web-1, team 999

- [ ] Sample flag submission through CTFd UI accepted correctly
  Log in as team-999, go to challenge [TEST] Web 1, submit the FLAG value from above
  Expected: CTFd shows "Correct!"

- [ ] Cross-team flag rejection verified (security check)
  Log in as team-1, get their FLAG env var for any challenge
  Log in as team-2 (different account), submit team-1's flag for the same challenge
  Expected: CTFd shows "Incorrect" — cross-team flag cryptographically rejected
  Then check: `curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" https://ctfd.infodays.net/admin/cheaters | jq .`
  Expected: cheaters table contains an entry for this cross-team attempt

- [ ] 4-pod cap verified: 5th activation returns correct error
  Activate 4 challenges for team-999, then attempt a 5th
  Expected: controller returns HTTP 409 or 429 with error message about max instances

- [ ] HTTP challenge URL format is correct (NodePort, plain HTTP)
  Activate a web challenge for team-999 and check the returned URL format.
  Expected: `http://challenges.infodays.net:<nodeport>` (not https://, not team-specific subdomain)
  Note: HTTP and TCP challenges share the same NodePort model — isolation is cryptographic only (HMAC flags per team)

---

## Security

- [ ] All 4 network isolation tests PASS
  `bash scripts/run-isolation-tests.sh`
  Expected: 4/4 tests PASS

- [ ] Controller API reachable from CTFd plugin
  `kubectl exec -n ctfd deployment/ctfd -- curl -s http://controller-api.ctfd.svc.cluster.local:80/health`
  Expected: HTTP 200

- [ ] Controller API rejects requests without valid X-Controller-Key header
  `kubectl port-forward -n ctfd svc/controller-api 18080:80 &amp; sleep 1 &amp;&amp; curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/status/0 -H "X-Controller-Key: wrongkey"; kill %1`
  Expected: HTTP 401

- [ ] ProxySQL backends healthy (not SHUNNED)
  `PROXYSQL_ADMIN_PASSWORD="$(kubectl get secret proxysql-admin -n ctfd -o jsonpath='{.data.PROXYSQL_ADMIN_PASSWORD}' | base64 -d)" && kubectl exec -n ctfd deployment/proxysql -- env MYSQL_PWD="$PROXYSQL_ADMIN_PASSWORD" mysql -h127.0.0.1 -P6032 -uadmin -e "SELECT hostgroup, srv_host, status, ConnUsed FROM stats.stats_mysql_connection_pool;"`
  Expected: one ONLINE entry for hostgroup 0 / `mysql.ctfd.svc.cluster.local`; NOT SHUNNED

- [ ] MySQL replica is healthy and serving ProxySQL reads
  `kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)" -e "SHOW REPLICA STATUS\G" 2>/dev/null | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind"`
  Expected if replica is enabled: Replica_IO_Running=Yes, Replica_SQL_Running=Yes, Seconds_Behind_Source=0 (or <5)
  ProxySQL config should route ordinary SELECTs to hostgroup 1 and writes/write-intent reads to hostgroup 0.

- [ ] Redis is a StatefulSet with PVC (not ephemeral Deployment)
  `kubectl get statefulset redis -n ctfd`
  Expected: redis StatefulSet, READY=1/1
  `kubectl get pvc redis-data-redis-0 -n ctfd`
  Expected: PVC bound, 1Gi

- [ ] CTFd session cookies are host-only
  `kubectl exec -n ctfd deployment/ctfd -- env | grep SESSION_COOKIE_DOMAIN || true`
  Expected: no `SESSION_COOKIE_DOMAIN` value, so CTFd cookies are not sent to challenge subdomains.

- [ ] Rate limiting active on CTFd ingress
  `kubectl get ingress ctfd -n ctfd -o jsonpath='{.metadata.annotations}'`
  Expected: `limit-rps: "20"` annotation present

- [ ] Login rate limiting ingress deployed
  `kubectl get ingress ctfd-login-ratelimit -n ctfd`
  Expected: ingress exists (5 rps limit on /login, /register, /api/v1/auth)

- [ ] PodDisruptionBudgets deployed
  `kubectl get pdb -n ctfd`
  Expected: ctfd-pdb (minAvailable 3), controller-api-pdb (minAvailable 3), mysql-pdb, redis-pdb

- [ ] Challenge namespace resource quotas in place
  `kubectl get resourcequota,limitrange -n challenges`
  Expected: challenges-quota (100 pods max) and challenges-limits present

- [ ] Pod security contexts enforced (no privilege escalation)
  `kubectl get deployment ctfd -n ctfd -o jsonpath='{.spec.template.spec.securityContext}'`
  Expected: runAsNonRoot=true

---

## Ops Readiness (Final Gate)

**⚠️ Do NOT open the event until all four items below are checked.**

- [ ] MySQL backup taken successfully
  `bash scripts/backup-mysql.sh`
  Expected: file `backups/ctfd-backup-YYYY-MM-DD_*.sql` created and non-empty

- [ ] Local secret and backup files are readable only by the operator
  `chmod 600 .env .ctfd.env .env.local data/teams.csv infra/terraform/terraform.tfvars k8s/ctfd/secrets.local.yaml 2>/dev/null || true; chmod 700 backups 2>/dev/null || true`
  Expected: credentials, player CSV, Terraform vars, and SQL dumps are not world-readable.

- [ ] Load test passed: error rate < 1% at 60 VUs (15 teams × 4 members); p95 < 3s for normal CTFd pages
  Note: p95 ~11-12s is normal due to K8s API roundtrip on first `activate` (pod scale-up). Error rate is the critical threshold, not raw latency.
  ```bash
  export K6_CTF_BASE_URL=https://ctfd.infodays.net
  export K6_CTF_CHALLENGE_ID=1
  export K6_CTF_MANIFEST_CHALLENGE=web-sqli
  # Generate player-account JSON from CSV (first 15 teams, up to 4 players each = up to 60 VUs total):
  export K6_CTF_TEAMS="$(python3 -c "
  import csv, json
  accounts = []
  team_ids = {}
  per_team = {}
  with open('data/teams.csv') as f:
      for row in csv.DictReader(f):
          team = row['team_name'].strip()
          player = row['player_name'].strip()
          if not team or not player:
              continue
          if team not in team_ids:
              if len(team_ids) >= 15:
                  continue
              team_ids[team] = len(team_ids) + 1
              per_team[team] = 0
          if per_team[team] >= 4:
              continue
          per_team[team] += 1
          accounts.append({
              'username': player,
              'password': row['password'].strip(),
              'team_id': str(team_ids[team]),
              'team_name': team,
              'team_index': team_ids[team] - 1,
          })
  print(json.dumps(accounts))
  ")"
  mkdir -p tests/load/results
  k6 run --out json=tests/load/results/pre-event-$(date +%Y%m%d-%H%M%S).json tests/load/k6-ctf-scenario.js
  ```
  Expected: k6 exits 0, both thresholds shown as ✓ in output
  Note: k6 script uses 60 VUs for 90 minutes. Login stagger is 1s per team (15s total ramp).

- [ ] Runbook reviewed by at least one team member
  Open `docs/event-day-runbook.md` and read through with a second team member

- [ ] Teardown command tested in staging (NOT production)
  `kubectl delete deployments,services,secrets,ingresses -l managed-by=ctf-controller -n challenges --dry-run=client`
  Expected: dry-run shows resources that would be deleted (no actual deletion)

---

**Sign-off**: _________________________________ Date: _____________
