# Tasks: Event Readiness & Runbook

**Input**: Design documents from `/specs/006-event-readiness-runbook/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅

**Organization**: Tasks grouped by user story. All 4 stories are independently deliverable.
**Tests**: Not requested — no test tasks generated.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Every task includes the exact file path to create or modify

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create directories and gitignore entries needed by all four deliverables.

- [x] T001 Create directory `tests/load/` (the load test script lives here). Also create `tests/load/results/` as a placeholder directory. Add a `.gitkeep` file inside `tests/load/results/` so git tracks the empty directory.
- [x] T002 Create directory `docs/` at the repository root. This directory will hold the pre-event checklist and event-day runbook.
- [x] T003 Create directory `backups/` at the repository root. Add a `.gitkeep` inside it. This directory will hold MySQL SQL dumps — it must not be committed, only the `.gitkeep`.
- [x] T004 Edit `.gitignore` at the repository root (read existing content first, then append). Add these three lines:
  ```
  backups/*.sql
  tests/load/results/*.json
  tests/load/results/*.txt
  ```
  Do NOT remove any existing entries. If `.gitignore` does not exist, create it.

**Checkpoint**: Directory structure exists. `ls tests/load/ docs/ backups/` shows the directories.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Read the existing scripts to understand the coding conventions, so that new scripts match the style.

- [x] T005 Read `scripts/deploy-challenge.sh` (an existing script in this repo). Note the shebang line, how it sets `set -euo pipefail`, how it defines error messages with `echo >&2`, and how it uses `kubectl`. The new `backup-mysql.sh` script (T009) MUST follow the same conventions.

**Checkpoint**: You understand the scripting conventions. User story implementation can begin.

---

## Phase 3: User Story 1 — Load Test Script (Priority: P1) 🎯 MVP

**Goal**: Produce `tests/load/k6-ctf-scenario.js` — a k6 script that simulates 50 concurrent players executing the full CTFd player journey for 5 minutes and enforces SLA thresholds.

**Independent Test**: Run `k6 run tests/load/k6-ctf-scenario.js` (with env vars set). k6 exits 0 if both thresholds pass; non-zero if either fails. The script itself must also pass `k6 validate` (syntax check).

**Context for this story**: k6 is a JavaScript load testing tool. Scripts export `options` (config) and a `default` function (one VU's logic). k6 provides `http`, `check`, and `cookiejar` modules. The CTFd login requires extracting a CSRF nonce from the HTML form before posting credentials. All 7 scenario steps are defined in `specs/006-event-readiness-runbook/contracts/load-test-scenario.md`.

### Implementation for User Story 1

- [x] T006 [US1] Create `tests/load/k6-ctf-scenario.js`. The file must:

  1. **Import** k6 modules at the top:
     ```js
     import http from 'k6/http';
     import { check, sleep } from 'k6';
     ```

  2. **Export options** with these exact values:
     ```js
     export const options = {
       vus: 50,
       duration: '5m',
       thresholds: {
         http_req_duration: ['p(95)<2000'],
         http_req_failed:   ['rate<0.01'],
       },
     };
     ```

  3. **Read environment variables** at the top of the file (outside the default function):
     ```js
     const BASE_URL     = __ENV.K6_CTF_BASE_URL    || 'https://ctfd.infodays.net';
     const USERNAME     = __ENV.K6_CTF_USERNAME;
     const PASSWORD     = __ENV.K6_CTF_PASSWORD;
     const CHALLENGE_ID = __ENV.K6_CTF_CHALLENGE_ID || '1';
     ```

  4. **Export default function** that runs all 7 steps in order for one VU iteration:

     **Step 1** — GET home page, extract CSRF nonce:
     ```js
     const homeRes = http.get(`${BASE_URL}/`);
     check(homeRes, { 'home page 200': (r) => r.status === 200 });
     // CTFd embeds the CSRF nonce in a hidden input: <input id="nonce" name="nonce" value="...">
     const nonceMatch = homeRes.body.match(/name="nonce"\s+value="([^"]+)"/);
     const nonce = nonceMatch ? nonceMatch[1] : '';
     ```

     **Step 2** — POST /login with credentials and nonce:
     ```js
     const loginRes = http.post(`${BASE_URL}/login`, {
       name: USERNAME,
       password: PASSWORD,
       nonce: nonce,
     });
     check(loginRes, { 'login success': (r) => r.status === 200 || r.status === 302 });
     ```

     **Step 3** — GET /challenges:
     ```js
     const challengesRes = http.get(`${BASE_URL}/challenges`);
     check(challengesRes, { 'challenges page 200': (r) => r.status === 200 });
     ```

     **Step 4** — Submit wrong flag:
     ```js
     const wrongFlagRes = http.post(
       `${BASE_URL}/api/v1/challenges/${CHALLENGE_ID}/attempt`,
       JSON.stringify({ submission: 'wrongflag' }),
       { headers: { 'Content-Type': 'application/json' } }
     );
     check(wrongFlagRes, { 'wrong flag attempt 200': (r) => r.status === 200 });
     ```

     **Step 5** — Submit correct flag (uses the known test flag for team-999/test-web-1):
     ```js
     // The correct flag is derived by the controller; for load test purposes
     // we submit a plausible-format flag — the test verifies the endpoint
     // responds (not that the flag is accepted).
     const correctFlagRes = http.post(
       `${BASE_URL}/api/v1/challenges/${CHALLENGE_ID}/attempt`,
       JSON.stringify({ submission: 'infodays{test}' }),
       { headers: { 'Content-Type': 'application/json' } }
     );
     check(correctFlagRes, { 'flag attempt responded': (r) => r.status === 200 });
     ```

     **Step 6** — Activate challenge instance via CTFd proxy:
     ```js
     const activateRes = http.post(
       `${BASE_URL}/controller-proxy/activate`,
       JSON.stringify({ team_id: 999, challenge_id: 'test-web-1' }),
       { headers: { 'Content-Type': 'application/json' } }
     );
     check(activateRes, { 'activate responded': (r) => r.status < 500 });
     ```

     **Step 7** — Check instance status:
     ```js
     const statusRes = http.get(`${BASE_URL}/controller-proxy/status/999`);
     check(statusRes, { 'status responded': (r) => r.status < 500 });

     sleep(1); // 1-second think time between iterations
     ```

  5. **Full file structure**: The file must be valid k6 ESM JavaScript. The export order is: imports → `options` export → `default` function export.

**Checkpoint**: `k6 validate tests/load/k6-ctf-scenario.js` exits 0 (no syntax errors). Running with `--dry-run` flag shows all 7 HTTP calls in the output.

---

## Phase 4: User Story 2 — Pre-Event Checklist (Priority: P1)

**Goal**: Produce `docs/pre-event-checklist.md` — a markdown checklist that an organizer walks through manually before opening the event. Every item includes the exact command to verify it.

**Independent Test**: Open the file. Every checkbox item must have an inline command or action in backticks that can be copy-pasted into a terminal.

**Context for this story**: The checklist is sourced directly from the Phase 6 spec in `.specify/Plan.md` lines 900–931. The four sections are: Infrastructure, CTFd Platform, Challenge Infrastructure, Ops Readiness. The Ops Readiness section is the final sign-off gate and must come last.

### Implementation for User Story 2

- [x] T007 [US2] Create `docs/pre-event-checklist.md` with this exact structure and content:

  ```markdown
  # InfoDays CTF — Pre-Event Checklist

  **Event**: InfoDays CTF | **Domain**: ctfd.infodays.net
  **Instructions**: Work through each section top-to-bottom. Check off each item as it passes.
  Do NOT open the event until every item in the Ops Readiness section is checked.

  ---

  ## Infrastructure

  - [ ] DOKS: all 4 nodes are Ready
    `kubectl get nodes`
    Expected: 4 nodes, STATUS=Ready

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

  - [ ] CTFd loads over HTTPS with valid TLS
    Open `https://ctfd.infodays.net` in a browser
    Expected: page loads, browser shows valid padlock

  - [ ] Admin login works
    Log in at `https://ctfd.infodays.net/login` with admin credentials
    Expected: redirected to admin dashboard

  - [ ] All team accounts created (import-teams.py ran successfully)
    `python3 scripts/import-teams.py --list --ctfd-url https://ctfd.infodays.net --admin-token $CTFD_ADMIN_TOKEN`
    Expected: all expected teams present

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

  - [ ] import_flags.py ran — all derived flags present in CTFd
    `curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" https://ctfd.infodays.net/api/v1/flags | jq '.data | length'`
    Expected: count matches total number of service challenges × teams

  - [ ] Sample end-to-end test: activate one Web, one Pwn, one Misc instance for team-999
    `curl -X POST http://controller-api.ctfd.svc.cluster.local:80/activate -H "X-Controller-Key: $CONTROLLER_KEY" -d '{"team_id":999,"challenge_id":"test-web-1"}'`
    (run from inside the cluster or use kubectl port-forward first)

  - [ ] Verify FLAG env var inside test pod matches CTFd stored flag
    `kubectl exec -n challenges deployment/team-999-test-web-1 -- printenv FLAG`
    Compare output with the flag stored in CTFd for challenge test-web-1, team 999

  - [ ] Sample flag submission through CTFd UI accepted correctly
    Log in as team-999, go to challenge [TEST] Web 1, submit the FLAG value from above
    Expected: CTFd shows "Correct!"

  - [ ] 4-pod cap verified: 5th activation returns correct error
    Activate 4 challenges for team-999, then attempt a 5th
    Expected: controller returns HTTP 409 or 429 with error message about max instances

  ---

  ## Security

  - [ ] All 4 network isolation tests PASS
    `bash infra/tests/run-isolation-tests.sh`
    Expected: 4/4 tests PASS

  - [ ] Controller API reachable from CTFd plugin
    `kubectl exec -n ctfd deployment/ctfd -- curl -s http://controller-api.ctfd.svc.cluster.local:80/health`
    Expected: HTTP 200

  - [ ] Controller API rejects requests without X-Controller-Key header
    `kubectl exec -n ctfd deployment/ctfd -- curl -s -o /dev/null -w "%{http_code}" http://controller-api.ctfd.svc.cluster.local:80/health -H "X-Controller-Key: wrongkey"`
    Expected: HTTP 401

  ---

  ## Ops Readiness (Final Gate)

  **⚠️ Do NOT open the event until all four items below are checked.**

  - [ ] MySQL backup taken successfully
    `bash scripts/backup-mysql.sh`
    Expected: file `backups/ctfd-backup-YYYY-MM-DD_*.sql` created and non-empty

  - [ ] Load test passed: p95 < 2s, error rate < 1%
    ```bash
    export K6_CTF_BASE_URL=https://ctfd.infodays.net
    export K6_CTF_USERNAME=team-999
    export K6_CTF_PASSWORD=<test-team-password>
    export K6_CTF_CHALLENGE_ID=<numeric-id-for-test-web-1>
    k6 run --out json=tests/load/results/pre-event-$(date +%Y%m%d-%H%M%S).json tests/load/k6-ctf-scenario.js
    ```
    Expected: k6 exits 0, both thresholds shown as ✓ in output

  - [ ] Runbook reviewed by at least one team member
    Open `docs/event-day-runbook.md` and read through with a second team member

  - [ ] Teardown command tested in staging (NOT production)
    `kubectl delete deployments,services,secrets,ingresses -l managed-by=ctf-controller -n challenges --dry-run=client`
    Expected: dry-run shows resources that would be deleted (no actual deletion)

  ---

  **Sign-off**: _________________________________ Date: _____________
  ```

**Checkpoint**: `docs/pre-event-checklist.md` exists. Every section has at least one item with an inline command.

---

## Phase 5: User Story 3 — MySQL Backup Script (Priority: P2)

**Goal**: Produce `scripts/backup-mysql.sh` — a Bash script that fetches the MySQL root password from a K8s Secret, runs `mysqldump` inside the MySQL pod, and saves the result to `backups/ctfd-backup-{timestamp}.sql`.

**Independent Test**: Run `bash scripts/backup-mysql.sh` against the live cluster. The script exits 0 and a `.sql` file appears in `backups/`. The file is non-empty and begins with `-- MySQL dump`.

**Context for this story**: The MySQL pod is not externally reachable (NetworkPolicy blocks ingress). The only way to run `mysqldump` is via `kubectl exec`. The MySQL root password is stored in K8s Secret `ctfd-secrets` (key: `MYSQL_ROOT_PASSWORD`) in namespace `ctfd`. See research decision R-003 in `specs/006-event-readiness-runbook/research.md`.

### Implementation for User Story 3

- [x] T008 [US3] Create `scripts/backup-mysql.sh`. Follow the same conventions as `scripts/deploy-challenge.sh` (shebang, `set -euo pipefail`, `echo >&2` for errors). The script must:

  1. **Shebang and safety flags**:
     ```bash
     #!/usr/bin/env bash
     set -euo pipefail
     ```

  2. **Define output directory and timestamp**:
     ```bash
     BACKUP_DIR="$(git rev-parse --show-toplevel)/backups"
     TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
     OUTPUT_FILE="${BACKUP_DIR}/ctfd-backup-${TIMESTAMP}.sql"
     mkdir -p "${BACKUP_DIR}"
     ```

  3. **Fetch MySQL root password from K8s Secret** (exit code 3 if this fails):
     ```bash
     echo "Fetching MySQL root password from K8s Secret ctfd-secrets..."
     MYSQL_ROOT_PASSWORD=$(kubectl get secret ctfd-secrets -n ctfd \
       -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' 2>/dev/null | base64 -d) || {
       echo "ERROR: Failed to read MYSQL_ROOT_PASSWORD from K8s Secret ctfd-secrets in namespace ctfd." >&2
       echo "Ensure kubectl is configured and the secret exists." >&2
       exit 3
     }
     ```

  4. **Verify MySQL pod is running** (exit code 1 if not ready):
     ```bash
     echo "Checking MySQL pod status..."
     MYSQL_POD=$(kubectl get pod -n ctfd -l app=mysql -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || {
       echo "ERROR: No MySQL pod found in namespace ctfd (label app=mysql)." >&2
       exit 1
     }
     POD_PHASE=$(kubectl get pod "${MYSQL_POD}" -n ctfd -o jsonpath='{.status.phase}')
     if [[ "${POD_PHASE}" != "Running" ]]; then
       echo "ERROR: MySQL pod ${MYSQL_POD} is not Running (phase: ${POD_PHASE})." >&2
       exit 1
     fi
     ```

  5. **Run mysqldump via kubectl exec** (exit code 2 if dump fails):
     ```bash
     echo "Running mysqldump on pod ${MYSQL_POD} → ${OUTPUT_FILE}"
     kubectl exec "${MYSQL_POD}" -n ctfd -- \
       mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" --single-transaction ctfd \
       > "${OUTPUT_FILE}" 2>/tmp/mysqldump-stderr || {
       echo "ERROR: mysqldump failed." >&2
       cat /tmp/mysqldump-stderr >&2
       rm -f "${OUTPUT_FILE}"
       exit 2
     }
     ```

  6. **Verify output and print success**:
     ```bash
     FILESIZE=$(wc -c < "${OUTPUT_FILE}")
     if [[ "${FILESIZE}" -lt 100 ]]; then
       echo "ERROR: Backup file is suspiciously small (${FILESIZE} bytes). Check mysqldump output." >&2
       exit 2
     fi
     echo "✓ Backup complete: ${OUTPUT_FILE} (${FILESIZE} bytes)"
     ```

- [x] T009 [US3] Make the backup script executable:
  ```bash
  chmod +x scripts/backup-mysql.sh
  ```
  This must be done as a separate step (edit the file, then run chmod, or set the git file mode).

**Checkpoint**: `bash scripts/backup-mysql.sh` exits 0 and a `.sql` file appears in `backups/`. Running it against a non-existent secret exits 3 with a clear error message.

---

## Phase 6: User Story 4 — Event-Day Runbook (Priority: P2)

**Goal**: Produce `docs/event-day-runbook.md` — a markdown operations runbook with four sections covering the full event lifecycle, including a prominent WARNING before any destructive commands.

**Independent Test**: Open the file. The four sections exist in order: Before Opening, During Event, End of Event, Teardown. The Teardown section contains a WARNING block before `terraform destroy`.

**Context for this story**: The exact commands for each operation are specified in `.specify/Plan.md` lines 933–963. The runbook must include every operation listed there. The WARNING block before `terraform destroy` must be visually prominent (use a blockquote or bold warning header).

### Implementation for User Story 4

- [x] T010 [US4] Create `docs/event-day-runbook.md` with this exact structure:

  ```markdown
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

  ### Add a new challenge mid-event

  ```bash
  # 1. Build and push the new challenge image
  bash scripts/push-challenge.sh <challenge-id> challenges/base-images/<type> <type>

  # 2. Add the challenge manifest to challenges/manifests/<challenge-id>.yaml

  # 3. Update the ConfigMap and restart the controller
  kubectl create configmap challenge-manifests \
    --from-file=challenges/manifests/ -n ctfd --dry-run=client -o yaml | kubectl apply -f -
  kubectl rollout restart deployment/controller-api -n ctfd

  # 4. Pre-spawn pods for the new challenge only
  kubectl exec -n ctfd deployment/controller-api -- \
    python3 bulk_spawn.py --challenge <challenge-id>
  ```

  ### Restart a broken team pod (manual)

  ```bash
  kubectl rollout restart deployment/team-{id}-{challenge-id} -n challenges
  ```

  Replace `{id}` with the numeric team ID and `{challenge-id}` with the challenge ID (e.g., `team-3-web-sqli`).

  ### Force-suspend a team's pod (admin action)

  ```bash
  kubectl patch deployment/team-{id}-{challenge-id} -n challenges \
    -p '{"spec":{"replicas":0}}'
  ```

  Use this to suspend a team that is abusing the infrastructure.

  ### Scale CTFd under unexpected load

  ```bash
  kubectl scale deployment/ctfd -n ctfd --replicas=3
  ```

  Scale back down after load subsides:
  ```bash
  kubectl scale deployment/ctfd -n ctfd --replicas=2
  ```

  ### Extend the event end time

  CTFd admin panel → **Configuration** → **End time** → update and save.

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
  ```

**Checkpoint**: `docs/event-day-runbook.md` exists. All four sections are present. The WARNING block appears before `terraform destroy`. Every command is in a fenced code block.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final checks that span all four deliverables.

- [x] T011 [P] Verify `tests/load/k6-ctf-scenario.js` has no syntax errors. If `k6` is installed locally, run `k6 validate tests/load/k6-ctf-scenario.js`. If not installed, read through the file and confirm: (a) it starts with `import` statements, (b) it exports `options` and a `default` function, (c) all 7 HTTP calls are present, (d) env vars are read via `__ENV`.

- [x] T012 [P] Verify `scripts/backup-mysql.sh` begins with `#!/usr/bin/env bash` and `set -euo pipefail`, has `chmod +x` applied (check with `ls -la scripts/backup-mysql.sh` — permissions must show `-rwxr-xr-x`), and references `kubectl`, `base64`, and `mysqldump`.

- [x] T013 [P] Verify `docs/pre-event-checklist.md` has exactly 4 top-level sections (Infrastructure, CTFd Platform, Challenge Infrastructure, Security, Ops Readiness — actually 5 sections as implemented), each section has at least one checkbox item, and the Ops Readiness section is last and contains the 4 required gate items.

- [x] T014 [P] Verify `docs/event-day-runbook.md` has exactly 4 top-level sections in this order: Before Opening, During Event, End of Event, Teardown. Confirm the `⚠️ WARNING` block appears before the `terraform destroy` command.

- [x] T015 Confirm that `backups/` and `tests/load/results/` are covered by `.gitignore` entries (open `.gitignore` and verify the lines from T004 are present). Confirm neither directory itself is gitignored — only the files inside them.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — reads existing script for style reference
- **User Stories (Phase 3–6)**: All depend on Phase 2; all four stories are **independent** of each other
- **Polish (Phase 7)**: Depends on all four user story phases being complete

### User Story Dependencies

- **US1 (P1) — Load Test**: Independent. Only file: `tests/load/k6-ctf-scenario.js`
- **US2 (P1) — Checklist**: Independent. Only file: `docs/pre-event-checklist.md`
- **US3 (P2) — Backup Script**: Independent. Only file: `scripts/backup-mysql.sh`
- **US4 (P2) — Runbook**: Independent. Only file: `docs/event-day-runbook.md`

All four user stories can be implemented in any order or in parallel after Phase 2.

### Parallel Opportunities

```
Phase 1 (T001–T004) → sequential (directory creation order)
Phase 2 (T005)      → single task
Phase 3–6           → ALL PARALLEL (different files, no cross-story dependencies)
  ┌── T006 (US1: k6 script)
  ├── T007 (US2: checklist)
  ├── T008–T009 (US3: backup script)
  └── T010 (US4: runbook)
Phase 7 (T011–T015) → ALL PARALLEL (read-only validation tasks)
```

---

## Implementation Strategy

### MVP First (US1 + US2 — both P1)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005)
3. Complete Phase 3: Load Test Script (T006) — **validates the SLA gate**
4. Complete Phase 4: Pre-Event Checklist (T007) — **validates the sign-off gate**
5. **STOP and VALIDATE**: Run `k6 validate` on T006; open T007 and verify all items have commands
6. Deliver US1 + US2 as MVP

### Incremental Delivery

1. Setup + Foundational → repo structure ready
2. US1 (load test) + US2 (checklist) → P1 stories done → event can be gate-checked
3. US3 (backup script) → MySQL backup tested against live cluster
4. US4 (runbook) → full operations documentation complete
5. Polish (T011–T015) → final cross-check

---

## Notes

- **File paths are exact**: Do not change directory names or file names — other scripts and documentation reference them.
- **k6 script**: The exact nonce regex (`name="nonce"\s+value="([^"]+)"`) was verified against CTFd's login form HTML. If CTFd's form changes, this regex may need updating.
- **Backup script**: The `base64 -d` flag works on Linux. On macOS use `base64 -D`. The script should use `-d` (Linux/DOKS default) since it runs on the operator's workstation connecting to a Linux cluster.
- **Checklist note**: The Security section was added as a 5th section (the spec listed it separately from Challenge Infrastructure). Task T013 in Polish should verify 5 sections, not 4.
- **Runbook WARNING**: The WARNING block uses markdown blockquote (`>`) syntax for visual emphasis. It must appear immediately before the `terraform destroy` code block.
- [P] tasks use different files and have no incomplete task dependencies — safe to parallelize.
- Each user story produces exactly one deliverable file (except US3 which produces one script file).
- Commit after each task or after each user story phase completes.
