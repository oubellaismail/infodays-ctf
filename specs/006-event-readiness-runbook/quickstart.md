# Quickstart: Event Readiness & Runbook

**Branch**: `006-event-readiness-runbook`

## Prerequisites

- Phases 1–5 fully deployed and validated on the live DOKS cluster
- `kubectl` configured with access to the `infodays-ctf` cluster
- `k6` installed on the operator workstation (`brew install k6` / `apt install k6`)
- Test team account (ID 999) created in CTFd

## 1. Run the Load Test

```bash
export K6_CTF_BASE_URL=https://ctfd.infodays.net
export K6_CTF_USERNAME=team-999
export K6_CTF_PASSWORD=<test-team-password>
export K6_CTF_CHALLENGE_ID=<numeric-ctfd-id-for-test-web-1>

k6 run \
  --out json=tests/load/results/run-$(date +%Y%m%d-%H%M%S).json \
  tests/load/k6-ctf-scenario.js
```

**Pass**: k6 exits 0, both thresholds green.
**Fail**: k6 exits non-zero, failing thresholds listed in output.

## 2. Take a MySQL Backup

```bash
bash scripts/backup-mysql.sh
# Output: backups/ctfd-backup-YYYY-MM-DD_HH-MM-SS.sql
```

## 3. Walk the Pre-Event Checklist

Open `docs/pre-event-checklist.md` and execute each item in order. Check off items as they pass. Do not open the event until all items in the **Ops Readiness** section are checked.

## 4. Use the Runbook on Event Day

Open `docs/event-day-runbook.md`. Follow the **Before Opening** section before starting the event. Keep the runbook open during the event for quick reference.

## Artifacts Created by This Phase

| Artifact | Purpose |
|----------|---------|
| `tests/load/k6-ctf-scenario.js` | Load test script |
| `tests/load/results/` | JSON run summaries (gitignored) |
| `scripts/backup-mysql.sh` | MySQL backup script |
| `docs/pre-event-checklist.md` | Pre-event sign-off gate |
| `docs/event-day-runbook.md` | Operations runbook |
| `backups/` | SQL dumps (gitignored) |
