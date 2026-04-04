# InfoDays CTF — Pre-Event Checklist

**Event**: InfoDays CTF | **Domain**: ctfd.infodays.net
**Instructions**: Work through each section top-to-bottom. Check off each item as it passes.
Do NOT open the event until every item in the Ops Readiness section is checked.

---

## Infrastructure

- [ ] DOKS: at least 3 nodes Ready (autoscaler range 3-8)
  `kubectl get nodes`
  Expected: 3-8 nodes, all STATUS=Ready
  Check autoscaler: `doctl kubernetes cluster node-pool get infodays-ctf infodays-workers --format AutoScale,MinNodes,MaxNodes,Count`
  Expected: AutoScale=true, MinNodes=3, MaxNodes=8

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

---

## Challenge Infrastructure

- [ ] bulk_spawn.py ran successfully — all challenge pods exist in challenges namespace
  `kubectl get deployments -n challenges --no-headers | wc -l`
  Expected: count matches (teams × challenges) total

- [ ] import_flags.py ran — one `team` flag row per service challenge in CTFd
  `curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" -H "Content-Type: application/json" https://ctfd.infodays.net/api/v1/flags | jq '[.data[] | select(.type=="team")] | length'`
  Expected: count equals number of service challenges (e.g., 3 for web-sqli, pwn-bof, misc-riddle)
  Note: type is `team` (not `static`) — one row covers all 50 teams via HMAC derivation

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

- [ ] HTTP challenge isolation: team-A cannot access team-B's HTTP challenge URL
  Log in as team-2, visit `https://team-1-web-sqli.challenges.infodays.net/`
  Expected: redirected to `https://ctfd.infodays.net/login` (nginx auth_request → 403 → redirect)
  Note: TCP challenges (nc) are NOT isolated by URL — HMAC flags prevent cross-team scoring anyway

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
  `kubectl exec -n ctfd deployment/proxysql -- mysql -h127.0.0.1 -P6032 -uadmin -padmin -e "SELECT hostgroup, srv_host, status, ConnUsed FROM stats.stats_mysql_connection_pool;"`
  Expected: TWO entries — hostgroup 0 (writer, mysql) and hostgroup 1 (reader, mysql-replica), both ONLINE; NOT SHUNNED

- [ ] MySQL replication running and caught up
  `kubectl exec -n ctfd mysql-replica-0 -- mysql -uroot -p"$(kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d)" -e "SHOW REPLICA STATUS\G" 2>/dev/null | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind"`
  Expected: Replica_IO_Running=Yes, Replica_SQL_Running=Yes, Seconds_Behind_Source=0 (or <5)

- [ ] Redis is a StatefulSet with PVC (not ephemeral Deployment)
  `kubectl get statefulset redis -n ctfd`
  Expected: redis StatefulSet, READY=1/1
  `kubectl get pvc redis-data-redis-0 -n ctfd`
  Expected: PVC bound, 1Gi

- [ ] SESSION_COOKIE_DOMAIN set to `.infodays.net` in CTFd pods (required for challenge isolation)
  `kubectl exec -n ctfd deployment/ctfd -- env | grep SESSION_COOKIE_DOMAIN`
  Expected: `SESSION_COOKIE_DOMAIN=.infodays.net`

---

## Ops Readiness (Final Gate)

**⚠️ Do NOT open the event until all four items below are checked.**

- [ ] MySQL backup taken successfully
  `bash scripts/backup-mysql.sh`
  Expected: file `backups/ctfd-backup-YYYY-MM-DD_*.sql` created and non-empty

- [ ] Load test passed: error rate < 1% at 200 VUs (50 teams × 4 members); p95 < 15s
  Note: p95 ~11-12s is normal due to K8s API roundtrip on first `activate` (pod scale-up). Error rate is the critical threshold, not raw latency.
  ```bash
  export K6_CTF_BASE_URL=https://ctfd.infodays.net
  export K6_CTF_CHALLENGE_ID=1
  export K6_CTF_MANIFEST_CHALLENGE=web-sqli
  # Generate teams JSON from CSV (50 teams, 4 VUs each = 200 VUs total):
  export K6_CTF_TEAMS="$(python3 -c "
  import csv, json; teams = []
  with open('data/teams.csv') as f:
      for i, row in enumerate(csv.DictReader(f), 1):
          teams.append({'username': row['team_name'], 'password': row['password'], 'team_id': str(i)})
  print(json.dumps(teams))
  ")"
  mkdir -p tests/load/results
  k6 run --out json=tests/load/results/pre-event-$(date +%Y%m%d-%H%M%S).json tests/load/k6-ctf-scenario.js
  ```
  Expected: k6 exits 0, both thresholds shown as ✓ in output
  Note: k6 script uses 200 VUs (4 per team). Login stagger is 1s per team (50s total ramp).

- [ ] Runbook reviewed by at least one team member
  Open `docs/event-day-runbook.md` and read through with a second team member

- [ ] Teardown command tested in staging (NOT production)
  `kubectl delete deployments,services,secrets,ingresses -l managed-by=ctf-controller -n challenges --dry-run=client`
  Expected: dry-run shows resources that would be deleted (no actual deletion)

---

**Sign-off**: _________________________________ Date: _____________
