# Research: Event Readiness & Runbook

**Branch**: `006-event-readiness-runbook` | **Date**: 2026-03-26

## Decision Log

---

### R-001: CTFd Login Flow for k6

**Decision**: Use k6's `http.cookieJar()` to handle session cookies; POST to `/login` with `name` (team username) and `password` form fields; capture the CSRF nonce from an initial GET to `/` by parsing `window.init.csrfNonce` from the HTML response or reading the `session` cookie. CTFd's Flask WTF CSRF token is embedded in the login form as a hidden `nonce` field — extract it with a regex before posting.

**Rationale**: CTFd uses Flask-WTF for CSRF protection. The login form includes a hidden `nonce` field whose value changes per session. k6 must extract it from the GET `/` response and replay it in the POST. Without this, all logins return 302 → challenge page but subsequent authenticated requests fail.

**Alternatives considered**:
- Skipping CSRF extraction and hoping CTFd's default config disables it — rejected: CTFd enables CSRF by default and the test should reflect real-world conditions.
- Using the CTFd API (`/api/v1/tokens`) for auth instead of form login — rejected: the spec requires simulating the browser login flow, not the API token flow.

---

### R-002: k6 Threshold and Output Syntax

**Decision**: Define thresholds in the `options` export using `http_req_duration` (p95) and `http_req_failed` (rate). Use `--out json=tests/load/results/run-{timestamp}.json` CLI flag for JSON output. The script itself does not manage the output path — the operator passes the flag.

**Rationale**: k6 threshold syntax is `{ 'http_req_duration': ['p(95)<2000'], 'http_req_failed': ['rate<0.01'] }`. These map directly to the spec's SLA requirements. JSON output is the standard machine-readable format for post-run analysis.

**Alternatives considered**:
- InfluxDB + Grafana output — rejected: monitoring stack is explicitly out of scope for v1.
- Custom summary handler in the script — rejected: adds complexity; CLI flag achieves the same result.

---

### R-003: MySQL Backup via kubectl exec

**Decision**: Use `kubectl exec deployment/mysql -n ctfd -- mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" ctfd` piped to a local file. The `MYSQL_ROOT_PASSWORD` is read from the Kubernetes Secret `ctfd-secrets` at script runtime using `kubectl get secret ctfd-secrets -n ctfd -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' | base64 -d`.

**Rationale**: The MySQL pod is not externally accessible (NetworkPolicy blocks all external ingress). `kubectl exec` is the only supported path. Reading the password from the K8s Secret at runtime avoids hardcoding credentials and follows the constitution's rule that secrets come from K8s only.

**Alternatives considered**:
- Port-forwarding and running mysqldump locally — rejected: requires a background process and is more complex than `kubectl exec`.
- Storing the MySQL password in a script env var — rejected: violates Constitution Principle I (secrets must come from K8s Secrets only).

---

### R-004: Load Test Test-Team Credentials

**Decision**: The load test script reads `K6_CTF_USERNAME` and `K6_CTF_PASSWORD` environment variables for the test team credentials. The test team account is team ID 999 (per constitution: test resources use `team_id=999`). The load test uses this single shared account for all 50 VUs — acceptable because the goal is infrastructure load, not per-team isolation.

**Rationale**: Hardcoding credentials in the script would be a security violation. Environment variables are the standard k6 mechanism for passing secrets (`__ENV.K6_CTF_USERNAME`). Using a single test account for all VUs avoids needing 50 test accounts and correctly simulates worst-case concurrent load on a single team's session.

**Alternatives considered**:
- Creating 50 separate test team accounts (one per VU) — rejected: excessive setup overhead; the goal is load on the infrastructure, not realistic per-team isolation.
- Hardcoding credentials — rejected: security violation.

---

### R-005: Load Test Challenge and Controller Targets

**Decision**: The load test uses challenge ID `test-web-1` (the test challenge from Phase 4/Plan 14b) and `team_id=999`. The controller activate and status calls target `http://controller-api.ctfd.svc.cluster.local:80` from inside the cluster — but since k6 runs externally, the load test uses the external CTFd proxy route `/controller-proxy/activate` and `/controller-proxy/status/999` instead.

**Rationale**: The controller API is not directly exposed externally. The CTFd plugin proxy (`/controller-proxy/*`) is the only external-facing path to the controller (as established in the Phase 3/5 architecture). The load test must use this path, which also exercises the CTFd plugin proxy — making it a more realistic end-to-end test.

**Alternatives considered**:
- Exposing the controller API via a separate Ingress for the load test — rejected: unnecessary infrastructure change; proxy path is already available and constitutionally sound.

---

### R-006: Pre-Event Checklist Structure

**Decision**: Four sections in order: Infrastructure → CTFd Platform → Challenge Infrastructure → Ops Readiness. Each item is a markdown checkbox with an inline command or action. The Ops Readiness section is the final gate and contains the four sign-off items from the spec (backup taken, load test passed, runbook reviewed, teardown tested in staging).

**Rationale**: The section order mirrors the dependency chain: infra must work before CTFd can load, CTFd must work before challenges can be verified, and all of the above must pass before ops readiness can be signed off. This ordering prevents wasted effort on downstream checks when upstream items are failing.

**Alternatives considered**:
- Alphabetical or arbitrary ordering — rejected: dependency-ordered structure is more efficient for a live event walkthrough.

---

### R-007: Event-Day Runbook Section Order

**Decision**: Four sections: Before Opening → During Event (common operations) → End of Event → Teardown. The Teardown section includes a prominent WARNING block before any `terraform destroy` commands. Each operation is a numbered procedure with exact commands.

**Rationale**: The section order mirrors the event timeline. Operators should be able to read top-to-bottom and know what to do at each stage. The WARNING before teardown guards against accidental infrastructure destruction.

**Alternatives considered**:
- Alphabetical by operation name — rejected: time-ordered is more usable during a live event.
- Separate runbook per section — rejected: a single file is simpler to distribute and reference.
