# Tasks: CTFd Platform Stack

**Feature**: `002-ctfd-platform-stack`
**Input**: Design documents from `/specs/002-ctfd-platform-stack/`

**Format**: `[ID] [P?] [Story] Description with file path`
- **[P]**: Parallelizable — different files, no blocking dependencies
- **[Story]**: User story label [US1]–[US5] (phases 3+ only)

**Key design docs** (read before implementing any task):
- Resource specs and env vars: `specs/002-ctfd-platform-stack/data-model.md`
- Script interfaces: `specs/002-ctfd-platform-stack/contracts/setup-ctfd-sh.md` and `contracts/import-teams-py.md`
- Deploy order: `specs/002-ctfd-platform-stack/quickstart.md`
- Constitution limits: `.specify/memory/constitution.md` §V (Resource & Cost Discipline)

---

## Phase 1: Setup

**Purpose**: Create directory layout and gitignore rules. No workload files yet.

- [x] T001 Create directory structure: `k8s/ctfd/`, `scripts/`, `data/` — empty directories only (add `.gitkeep` if needed)
- [x] T002 [P] Add two entries to `.gitignore`: `k8s/ctfd/secrets.local.yaml` and `data/teams.csv` — these files hold real credentials and must never be committed

**Checkpoint**: Directories exist; running `git status` does not track `secrets.local.yaml` or `teams.csv`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Secret template and supplementary NetworkPolicies. Both must exist before any workload is applied.

**⚠️ CRITICAL**: Without T004, CTFd pods cannot resolve hostnames or connect to MySQL/Redis. Phase 1 Terraform already created `default-deny-all`, but it left CTFd's egress to its own backends unallowed.

**Background — what Phase 1 Terraform already created (do NOT recreate):**
- `default-deny-all` NetworkPolicy (Ingress + Egress) in namespace `ctfd`
- `allow-ctfd-mysql` — MySQL ingress from CTFd pods ✅
- `allow-ctfd-redis` — Redis ingress from CTFd pods ✅
- `allow-ingress-to-ctfd` — ingress-nginx → CTFd port 8000 ✅
- `allow-ctfd-egress-internet` — CTFd egress to 0.0.0.0/0:443 ✅

**What Phase 2 must add (three missing egress rules):**
1. DNS egress — all pods in `ctfd` namespace → `kube-system` namespace, ports 53 UDP and TCP
2. CTFd → MySQL egress — pods with label `app: ctfd` → pods with label `app: mysql`, TCP 3306
3. CTFd → Redis egress — pods with label `app: ctfd` → pods with label `app: redis`, TCP 6379

- [x] T003 Create `k8s/ctfd/secrets.yaml` — Kubernetes Secret named `ctfd-secrets` in namespace `ctfd`, type `Opaque`, with these keys all set to the placeholder value `CHANGE_ME`: `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `SECRET_KEY`, `MAIL_PASSWORD`, `CTF_MASTER_SECRET`. Add a YAML comment at the top: "# Template only. Copy to secrets.local.yaml, fill real values, then apply secrets.local.yaml. Never apply this file directly."
- [x] T004 Create `k8s/ctfd/networkpolicy.yaml` — three NetworkPolicy resources separated by `---` in namespace `ctfd`: (1) `allow-ctfd-egress-dns`: podSelector `{}` (all pods), egress to namespaceSelector `kubernetes.io/metadata.name: kube-system` on port 53 UDP and TCP, policyTypes Egress; (2) `allow-ctfd-egress-mysql`: podSelector `app: ctfd`, egress to podSelector `app: mysql` on port 3306 TCP, policyTypes Egress; (3) `allow-ctfd-egress-redis`: podSelector `app: ctfd`, egress to podSelector `app: redis` on port 6379 TCP, policyTypes Egress

**Checkpoint**: Both files are valid YAML (`kubectl apply --dry-run=client -f k8s/ctfd/networkpolicy.yaml` passes). Secret template is committed with placeholder values only.

---

## Phase 3: User Story 1 — CTFd Platform Accessible (Priority: P1) 🎯 MVP

**Goal**: CTFd is live at `https://ctfd.infodays.net` with a valid TLS certificate, backed by MySQL and Redis.

**Independent Test**: After applying all manifests, `curl -I https://ctfd.infodays.net` returns HTTP 200; `openssl s_client -connect ctfd.infodays.net:443` shows a valid cert. US4 (data persistence) is satisfied by the MySQL PVC created in T006 — no separate implementation.

**Resource limits (constitutional — do not change):**
| Component | CPU limit | RAM limit |
|-----------|-----------|-----------|
| CTFd (each replica) | 0.5 | 512Mi |
| MySQL | 0.5 | 1Gi |
| Redis | 0.1 | 256Mi |

**Exact image tags to use:** `ctfd/ctfd:latest`, `mysql:8`, `redis:7-alpine`

**Service naming (exact — used by init container and DATABASE_URL):**
- CTFd service: `ctfd-service` — port 80, targetPort 8000
- MySQL service: `mysql` — port 3306
- Redis service: `redis` — port 6379

- [x] T005 [P] [US1] Create `k8s/ctfd/services.yaml` — three ClusterIP Service resources in one file (separated by `---`), all in namespace `ctfd`: `ctfd-service` (selector `app: ctfd`, port 80 → targetPort 8000), `mysql` (selector `app: mysql`, port 3306), `redis` (selector `app: redis`, port 6379)
- [x] T006 [P] [US1] Create `k8s/ctfd/mysql-statefulset.yaml` — StatefulSet named `mysql` in namespace `ctfd`, image `mysql:8`, replicas 1, label `app: mysql`; env vars from Secret `ctfd-secrets`: `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` as secretKeyRef; env var `MYSQL_USER` as literal value `ctfd`; resources: limits cpu `500m` memory `1Gi`; volumeClaimTemplate named `mysql-data`, accessMode ReadWriteOnce, storage `10Gi`, storageClassName `do-block-storage`; mount the PVC at `/var/lib/mysql`
- [x] T007 [P] [US1] Create `k8s/ctfd/redis-deployment.yaml` — Deployment named `redis` in namespace `ctfd`, image `redis:7-alpine`, replicas 1, label `app: redis`, no environment variables, no PVC, resources: limits cpu `100m` memory `256Mi`
- [x] T008 [US1] Create `k8s/ctfd/deployment.yaml` — Deployment named `ctfd` in namespace `ctfd`, image `ctfd/ctfd:latest`, replicas 2, label `app: ctfd`; initContainer named `wait-for-mysql` using image `busybox`, command `["sh", "-c", "until nc -z mysql 3306; do echo waiting for mysql; sleep 2; done"]`; environment variables: `DATABASE_URL` literal `mysql+pymysql://ctfd:$(MYSQL_PASSWORD)@mysql/ctfd`, `REDIS_URL` literal `redis://redis:6379`, `SECRET_KEY` from secretKeyRef `ctfd-secrets` key `SECRET_KEY`, `SERVER_SENT_EVENTS` literal `false`, `WORKERS` literal `4`, `MAIL_SERVER`/`MAIL_PORT`/`MAIL_USERNAME`/`MAILFROM_ADDR` as empty string literals (operators override at deploy), `MAIL_PASSWORD` from secretKeyRef `ctfd-secrets` key `MAIL_PASSWORD`, `MYSQL_PASSWORD` from secretKeyRef `ctfd-secrets` key `MYSQL_PASSWORD` (needed for DATABASE_URL interpolation); livenessProbe httpGet path `/healthcheck` port 8000 initialDelaySeconds 30 periodSeconds 10; readinessProbe httpGet path `/healthcheck` port 8000 initialDelaySeconds 10 periodSeconds 5; resources: limits cpu `500m` memory `512Mi`
- [x] T009 [US1] Create `k8s/ctfd/ingress.yaml` — Ingress named `ctfd-ingress` in namespace `ctfd`, ingressClassName `nginx`, annotations: `cert-manager.io/cluster-issuer: letsencrypt-prod`; spec: tls entry with hosts `[ctfd.infodays.net]` secretName `ctfd-tls`; rules: host `ctfd.infodays.net`, path `/` pathType Prefix, backend service name `ctfd-service` port number 80

**Checkpoint**: Apply in this order: `secrets.local.yaml` → `services.yaml` → `mysql-statefulset.yaml` → `redis-deployment.yaml` → `networkpolicy.yaml` → `deployment.yaml` → `ingress.yaml`. All pods reach Running state. `https://ctfd.infodays.net` shows CTFd login page.

---

## Phase 4: User Story 2 — Admin Configures Platform (Priority: P2)

**Goal**: `setup-ctfd.sh` configures CTFd event settings via API — no manual UI steps required.

**Independent Test**: Export `CTFD_URL` and `CTFD_ADMIN_TOKEN`, run `bash scripts/setup-ctfd.sh`, verify exit code 0 and check CTFd admin panel shows: event name = "InfoDays CTF", team mode = on, registration = disabled.

**CTFd API notes for implementer:**
- Health check endpoint: `GET /healthcheck` — returns 200 when ready
- Configuration endpoint: `PATCH /api/v1/configs` — accepts JSON body with key-value pairs
- Relevant config keys: `ctf_name`, `team_mode` (value `"teams"`), `registration_visibility` (value `"private"`)
- Auth header: `Authorization: Token $CTFD_ADMIN_TOKEN` and `Content-Type: application/json`
- All requests use `curl` — no Python, no jq required
- Full interface spec: `specs/002-ctfd-platform-stack/contracts/setup-ctfd-sh.md`

- [x] T010 [US2] Create `scripts/setup-ctfd.sh` — Bash script implementing the full contract in `specs/002-ctfd-platform-stack/contracts/setup-ctfd-sh.md`: read env vars (`CTFD_URL`, `CTFD_ADMIN_TOKEN`, optional `CTFD_EVENT_NAME` defaulting to "InfoDays CTF", `CTFD_FLAG_FORMAT` defaulting to "infodays{...}", `CTFD_START_TIME`, `CTFD_END_TIME`, `POLL_INTERVAL` defaulting to 5, `POLL_TIMEOUT` defaulting to 300); poll `/healthcheck` in a loop (exit 1 on timeout); configure via `PATCH /api/v1/configs` for `ctf_name`, `team_mode=teams`, `registration_visibility=private`; set start/end time if env vars provided; each curl call checks HTTP status and exits 2 on failure; print progress line for each step; idempotent

**Checkpoint**: `CTFD_URL=https://ctfd.infodays.net CTFD_ADMIN_TOKEN=<token> bash scripts/setup-ctfd.sh` exits 0. Re-running exits 0 again without errors.

---

## Phase 5: User Story 3 — Admin Imports Teams (Priority: P3)

**Goal**: Admin bulk-creates team accounts from CSV; script is idempotent and prints a clear summary.

**Independent Test**: Run `python scripts/import-teams.py --dry-run --ctfd-url X --admin-token Y data/teams-template.csv` — exits 0. Run live with a 5-row CSV — 5 teams created, exit 0. Run again — 5 "already exists", exit 0.

**CTFd API notes for implementer:**
- List teams: `GET /api/v1/teams?name=<team_name>` — check if `data` array is empty
- Create team: `POST /api/v1/teams` with JSON body `{"name": ..., "email": ..., "password": ...}`
- Auth header: `Authorization: Token <admin_token>` and `Content-Type: application/json`
- Use `requests` library — do not use `urllib` or `http.client`
- Full interface spec: `specs/002-ctfd-platform-stack/contracts/import-teams-py.md`

- [x] T011 [US3] Create `scripts/import-teams.py` — Python 3.11+ script implementing the full contract in `specs/002-ctfd-platform-stack/contracts/import-teams-py.md`: argparse with positional `csv_file`, `--ctfd-url`, `--admin-token`, `--dry-run`; read CSV using `csv.DictReader`; validate each row (non-empty name/password, email contains `@`, password ≥ 8 chars); for each valid row check existence via CTFd API then create or skip; for each invalid row record as failed immediately; `--dry-run` skips API calls and prints "would create"; print `[N/total] Team Name — created/skipped/failed (reason)` per row; print `Summary: N created, N skipped, N failed.` at end; exit codes 0/1/2/3 per contract
- [x] T012 [P] [US3] Create `data/teams-template.csv` — CSV file with header row `team_name,email,password` and one example data row: `Team Name Here,team@example.com,ChangeThisPassword1`

**Checkpoint**: `python scripts/import-teams.py --help` prints usage. Dry-run with `teams-template.csv` shows "would create 1 team".

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Acceptance test suite covering US1–US5, and verification of the complete deployment.

**Notes**:
- US4 (data persistence) has no extra code: MySQL PVC in T006 already provides persistence. The acceptance test verifies it.
- US5 (network isolation): no additional policy needed. Phase 1 default-deny + Phase 2 supplementary policies provide isolation. Test verifies it.

- [x] T013 Create `infra/tests/validate-ctfd.sh` — Bash acceptance test script with `set -euo pipefail`, a `check()` helper that prints `[PASS]` or `[FAIL]` and sets a failure flag, and 5 checks: **(1 — TLS + HTTP)** `curl --fail -s -o /dev/null https://ctfd.infodays.net` succeeds AND `openssl s_client -connect ctfd.infodays.net:443 -brief 2>&1 | grep -q "Verification: OK"` succeeds; **(2 — Login page)** `curl -s https://ctfd.infodays.net` contains the string `CTFd`; **(3 — Persistence)** create a test flag via CTFd API, then `kubectl -n ctfd rollout restart deployment/ctfd`, wait for rollout, re-fetch the flag and verify it still exists; **(4 — Network isolation)** `kubectl -n ctfd exec deploy/ctfd -- nc -z -w2 <any-pod-ip-in-challenges-namespace> 80 2>&1 | grep -qv "succeeded"` — connection must NOT succeed (get challenge pod IP via `kubectl -n challenges get pods -o jsonpath`); **(5 — MySQL accessible)** `kubectl -n ctfd exec statefulset/mysql -- mysql -u ctfd -p"$MYSQL_PASSWORD" -e "SELECT 1"` exits 0; print overall PASS or FAIL at end; exit 1 if any check failed

**Checkpoint**: `bash infra/tests/validate-ctfd.sh` passes all 5 checks against the live cluster.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: After Phase 1 — T003 and T004 can run in parallel
- **US1 (Phase 3)**: After Phase 2 — T005, T006, T007 can run in parallel; T008 after T005+T006 (needs service name `mysql` and secret key names); T009 after T005 (needs service name `ctfd-service`)
- **US2 (Phase 4)**: Can be written during Phase 3; requires live CTFd for full validation
- **US3 (Phase 5)**: Can be written during Phase 3/4; requires configured CTFd (US2 done) for live validation — T011 and T012 can run in parallel
- **Polish (Phase 6)**: After Phase 5 — requires all workloads running

### User Story Delivery Status

| Story | Implementation | Satisfied by |
|-------|---------------|-------------|
| US1 — Platform accessible | Phase 3 (T005–T009) | Direct implementation |
| US2 — Admin configures | Phase 4 (T010) | Direct implementation |
| US3 — Team import | Phase 5 (T011–T012) | Direct implementation |
| US4 — Data persistence | Phase 3 (T006) | MySQL PVC in StatefulSet |
| US5 — Network isolation | Phase 2 (T004) | Supplementary egress-only NetworkPolicies leave challenges namespace unreachable |

### Parallel Opportunities

- T003 ‖ T004
- T005 ‖ T006 ‖ T007
- T008 and T009 can overlap (T009 only needs `ctfd-service` name from T005)
- T011 ‖ T012

---

## Parallel Example: Phase 3 (US1)

```bash
# Start all three at the same time:
Task T005: "Create k8s/ctfd/services.yaml"
Task T006: "Create k8s/ctfd/mysql-statefulset.yaml"
Task T007: "Create k8s/ctfd/redis-deployment.yaml"

# Once T005 is done, start concurrently:
Task T008: "Create k8s/ctfd/deployment.yaml"
Task T009: "Create k8s/ctfd/ingress.yaml"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (T001–T002)
2. Complete Phase 2 (T003–T004)
3. Complete Phase 3 (T005–T009)
4. **STOP and VALIDATE**: Apply manifests, verify `https://ctfd.infodays.net` shows CTFd login page
5. US4 already satisfied by T006 (MySQL PVC)

### Incremental Delivery

1. T001→T004: Foundation ready
2. T005→T009: CTFd accessible + persistent (MVP) ← demo-able milestone
3. T010: Event configured (team mode, registration disabled)
4. T011→T012: Teams importable from CSV
5. T013: All 5 acceptance checks passing

### Solo Execution Order

```
T001 → T002
     ↓
T003 ‖ T004
     ↓
T005 ‖ T006 ‖ T007
     ↓
T008 ‖ T009
     ↓
T010
     ↓
T011 ‖ T012
     ↓
T013
```

---

## Notes

- All K8s manifest files live in `k8s/ctfd/` and are applied with `kubectl apply -f`
- `k8s/ctfd/secrets.local.yaml` (real values) is gitignored — never commit it
- `data/teams.csv` (real team data) is gitignored — never commit it
- All resources must target namespace `ctfd` — it already exists from Phase 1 Terraform
- Resource limits are constitutional constraints — do not change them
- CTFd internal port is **8000** (not 80); the Service maps port 80 → targetPort 8000
- The init container uses the DNS name `mysql` (from the Service) — not an IP address
- `MYSQL_PASSWORD` must be injected as an env var so `DATABASE_URL` can use `$(MYSQL_PASSWORD)` substitution in T008
- Phase 1 Terraform already manages the namespace, default-deny policies, and ingress-side allows — do not duplicate these in `k8s/ctfd/networkpolicy.yaml`
