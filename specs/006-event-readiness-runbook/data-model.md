# Data Model: Event Readiness & Runbook

**Branch**: `006-event-readiness-runbook` | **Date**: 2026-03-26

This phase produces no persistent data schema. All deliverables are files (scripts and documents). The relevant "data" is the structure of inputs and outputs consumed or produced by each deliverable.

---

## Load Test Script

**File**: `tests/load/k6-ctf-scenario.js`

### Inputs (environment variables)

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `K6_CTF_USERNAME` | string | Yes | Test team username (team ID 999) |
| `K6_CTF_PASSWORD` | string | Yes | Test team password |
| `K6_CTF_BASE_URL` | string | Yes | CTFd base URL (e.g., `https://ctfd.infodays.net`) |
| `K6_CTF_CHALLENGE_ID` | string | No | Challenge ID to activate (default: `test-web-1`) |

### Runtime state per VU

| Field | Type | Description |
|-------|------|-------------|
| `jar` | CookieJar | Per-VU session cookie store |
| `csrfNonce` | string | CSRF token extracted from login page |
| `sessionCookie` | string | Authenticated session cookie |

### Output (JSON result file)

| Field | Type | Description |
|-------|------|-------------|
| `metrics.http_req_duration.values.p(95)` | number (ms) | 95th-percentile response time |
| `metrics.http_req_failed.values.rate` | number (0–1) | Fraction of failed requests |
| `thresholds` | object | Pass/fail per threshold name |

### k6 Options

| Option | Value |
|--------|-------|
| `vus` | 50 |
| `duration` | `5m` |
| `thresholds.http_req_duration` | `p(95) < 2000` |
| `thresholds.http_req_failed` | `rate < 0.01` |

---

## MySQL Backup Script

**File**: `scripts/backup-mysql.sh`

### Inputs

| Source | Variable | Description |
|--------|----------|-------------|
| K8s Secret `ctfd-secrets` | `MYSQL_ROOT_PASSWORD` | MySQL root password, fetched at runtime via kubectl |
| Environment | `KUBECONFIG` (optional) | kubectl config path; uses default if unset |

### Output

| Path | Format | Description |
|------|--------|-------------|
| `backups/ctfd-backup-{YYYY-MM-DD_HH-MM-SS}.sql` | SQL text | Full mysqldump of the `ctfd` database |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Backup succeeded, file written |
| 1 | MySQL pod not found or not ready |
| 2 | mysqldump failed (non-zero exit from exec) |
| 3 | kubectl secret fetch failed |

---

## Pre-Event Checklist

**File**: `docs/pre-event-checklist.md`

### Sections and item counts

| Section | Items | Verification method |
|---------|-------|---------------------|
| Infrastructure | 4 | kubectl + doctl commands |
| CTFd Platform | 5 | Browser + kubectl commands |
| Challenge Infrastructure | 6 | kubectl + manual test |
| Ops Readiness (final gate) | 4 | Script runs + human review |

### Ops Readiness gate (required before event opens)

| Item | How to verify |
|------|---------------|
| MySQL backup taken | `ls -lh backups/ctfd-backup-*.sql` shows recent file |
| Load test passed | k6 output shows both thresholds green |
| Runbook reviewed | At least one team member signs off verbally |
| Teardown tested in staging | `kubectl delete` teardown run against non-production namespace |

---

## Event-Day Runbook

**File**: `docs/event-day-runbook.md`

### Sections

| Section | Operations documented |
|---------|----------------------|
| Before Opening | Verify systems green; open event in CTFd |
| During Event | Add challenge, restart pod, suspend team, scale CTFd, extend time |
| End of Event | Freeze scoreboard, announce winners, export CSV, final backup |
| Teardown | Delete challenge resources, full `terraform destroy` with WARNING |

### Irreversible operations (require explicit confirmation)

| Operation | Risk | Warning in runbook |
|-----------|------|--------------------|
| `terraform destroy` | Destroys DOKS cluster, DOCR, load balancer, DNS | Prominent WARNING block before command |
| `kubectl delete` on challenges namespace | Deletes all team pods and secrets | Noted as post-event only |
