# Feature Specification: Event Readiness & Runbook

**Feature Branch**: `006-event-readiness-runbook`
**Created**: 2026-03-26
**Status**: Draft
**Input**: User description: "Phase 6 — Event Readiness & Runbook"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Load Test Verification (Priority: P1)

An event organizer runs a load test against the live CTFd platform and challenge controller before the event starts to confirm the system can handle 50 concurrent teams without degrading. The test simulates the full player journey — logging in, browsing challenges, submitting flags, and activating challenge instances — and must pass defined thresholds.

**Why this priority**: If the platform cannot sustain load under realistic conditions, the event fails for all participants. This is the hardest gate to pass and must be validated first.

**Independent Test**: Can be tested end-to-end by running the load test script against a staging or production cluster and checking the output summary for pass/fail against the p95 < 2s and error rate < 1% thresholds.

**Acceptance Scenarios**:

1. **Given** the CTFd platform and controller are deployed and running, **When** 50 virtual users simultaneously execute the full player scenario for 5 minutes, **Then** 95th-percentile response time is below 2 seconds and the overall request failure rate is below 1%.
2. **Given** the load test completes, **When** results are saved, **Then** a JSON summary file is written to `tests/load/results/` with all threshold outcomes recorded.
3. **Given** any threshold is breached, **When** the test finishes, **Then** the exit code is non-zero and the failing thresholds are clearly identified in the output.

---

### User Story 2 - Pre-Event Checklist Walkthrough (Priority: P1)

An event organizer walks through a structured checklist before the event opens, verifying every infrastructure component, CTFd configuration item, challenge deployment, security control, and operational readiness item. The checklist is the gate to opening the event.

**Why this priority**: A missed configuration (wrong flag format, disabled team accounts, expired TLS cert, failing network isolation) can silently break the entire event. The checklist makes every check explicit and auditable.

**Independent Test**: Can be tested by opening `docs/pre-event-checklist.md` and manually executing each item against the live cluster, checking off items as they pass.

**Acceptance Scenarios**:

1. **Given** the cluster is provisioned and all Phase 1–5 deliverables are deployed, **When** an organizer follows the pre-event checklist, **Then** every item can be verified with the documented command or action, and a completed checklist confirms the system is event-ready.
2. **Given** a check fails (e.g., TLS certificate is expiring, or bulk_spawn was not run), **When** the organizer sees the failure, **Then** the checklist item provides enough context to identify and resolve the issue.
3. **Given** all checklist items pass, **When** the organizer signs off, **Then** the event is cleared to open.

---

### User Story 3 - MySQL Backup (Priority: P2)

An event organizer takes a verified MySQL backup before the event starts and after it ends, ensuring that all team accounts, scores, and flag submissions can be recovered in the event of data loss.

**Why this priority**: Losing CTFd data mid-event (scores, flag submissions, team accounts) is unrecoverable without a backup. The script must work reliably with one command.

**Independent Test**: Can be tested independently by running `scripts/backup-mysql.sh` against the live cluster and confirming that a `.sql` file is produced in `backups/` and is non-empty and valid.

**Acceptance Scenarios**:

1. **Given** the MySQL pod is running, **When** the backup script is executed, **Then** a timestamped `.sql` file is created in `backups/` within 60 seconds.
2. **Given** the backup file is produced, **When** an organizer inspects it, **Then** it contains valid SQL that could be used to restore the database.
3. **Given** the MySQL pod is not running or unreachable, **When** the backup script is executed, **Then** it exits with a non-zero code and prints a clear error message.

---

### User Story 4 - Event-Day Operations (Priority: P2)

An event organizer or on-call admin uses the event-day runbook to handle common operations during the event: opening the event, restarting broken pods, suspending misbehaving teams, scaling CTFd under unexpected load, extending time, freezing the scoreboard at the end, exporting results, and tearing down infrastructure.

**Why this priority**: Without a runbook, any incident during the event requires real-time debugging under pressure. The runbook converts known scenarios into one-command resolutions.

**Independent Test**: Can be tested by walking through at least 3 runbook scenarios in a staging environment: force-suspending a team pod, scaling CTFd, and running the teardown commands against non-production resources.

**Acceptance Scenarios**:

1. **Given** the event is running and a team's challenge pod is broken, **When** an admin follows the runbook's "restart broken pod" procedure, **Then** the pod is restarted with a single command and resumes serving within 60 seconds.
2. **Given** unexpected load causes CTFd latency to rise, **When** an admin follows the runbook's "scale CTFd" procedure, **Then** CTFd replicas are increased with one command and latency drops.
3. **Given** the event ends, **When** an admin follows the end-of-event section in order, **Then** the scoreboard is frozen, scores are exported to CSV, and a final MySQL backup is taken before teardown.
4. **Given** the teardown section is reached, **When** an admin runs the infrastructure destroy command, **Then** a warning is displayed confirming the irreversible nature of the action before proceeding.

---

### Edge Cases

- What happens when the load test is run before `bulk_spawn.py` has been executed (no challenge pods exist)?
- How does the backup script behave if the `backups/` directory does not exist on the host?
- What if the load test target domain is unreachable (DNS not resolving, TLS not provisioned)?
- What if a checklist item cannot be verified because a dependency from an earlier phase is incomplete?
- What if the teardown command is run while the event is still active?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a load test script at `tests/load/k6-ctf-scenario.js` that simulates 50 concurrent virtual users for 5 minutes, executing the full player scenario: home page, login, challenge list, flag submission (wrong then correct), controller activate, and controller status check.
- **FR-002**: The load test MUST enforce thresholds: 95th-percentile response time below 2 seconds and request failure rate below 1%, and MUST exit with a non-zero code if either threshold is breached.
- **FR-003**: The load test MUST save a JSON results summary to `tests/load/results/` on each run.
- **FR-004**: The system MUST provide a MySQL backup script at `scripts/backup-mysql.sh` that connects to the running MySQL pod, executes a full database dump, and saves the output as `backups/ctfd-backup-{timestamp}.sql`.
- **FR-005**: The backup script MUST exit with a non-zero code and a clear error message if the MySQL pod is unreachable or the dump fails.
- **FR-006**: The system MUST provide a pre-event checklist at `docs/pre-event-checklist.md` covering four sections: infrastructure, CTFd platform, challenge infrastructure, and ops readiness.
- **FR-007**: Each checklist item MUST include the specific command or action needed to verify it, so an organizer with cluster access can execute it without consulting additional documentation.
- **FR-008**: The checklist ops readiness section MUST require all four of the following before sign-off: MySQL backup taken, load test passed, runbook reviewed by at least one team member, teardown tested in staging.
- **FR-009**: The system MUST provide an event-day runbook at `docs/event-day-runbook.md` with four sections: before opening, during the event (common operations), end of event, and teardown.
- **FR-010**: Each runbook operation MUST document the exact commands to execute.
- **FR-011**: The runbook teardown section MUST include a prominent WARNING that infrastructure destroy is irreversible and requires explicit team confirmation before proceeding.

### Key Entities

- **Load Test Script**: A runnable test definition encoding the full player journey as a sequence of HTTP requests with configurable thresholds, targeting the live CTFd domain and controller.
- **Load Test Result**: A timestamped JSON file capturing per-request metrics and threshold pass/fail outcomes for a single test run.
- **MySQL Backup**: A timestamped SQL dump of the CTFd database, suitable for restoring the full platform state.
- **Pre-Event Checklist**: A markdown document with discrete, independently verifiable items organized by subsystem, used as a sign-off gate before the event opens.
- **Event-Day Runbook**: A markdown document with step-by-step operational procedures for opening, managing, closing, and tearing down the event.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The load test passes its thresholds — 95th-percentile response time below 2 seconds and request failure rate below 1% — when run against the live cluster with 50 concurrent virtual users for 5 minutes.
- **SC-002**: The MySQL backup script produces a valid, non-empty `.sql` file within 60 seconds on every successful run.
- **SC-003**: An organizer with cluster access can complete the entire pre-event checklist without consulting any documentation outside the checklist itself.
- **SC-004**: At least 3 runbook scenarios (force-suspend a pod, scale CTFd, teardown challenges) are manually verified to work as documented before the event opens.
- **SC-005**: The end-to-end pre-event checklist is completed on the live cluster with all items passing at least once before the event opens.

## Scope

### In Scope

- Load test script covering the 7-step player scenario with threshold enforcement and JSON result output
- MySQL backup shell script with error handling
- Pre-event checklist document (infrastructure, CTFd platform, challenge infra, ops readiness)
- Event-day runbook (before opening, during event, end of event, teardown)

### Out of Scope

- Alerting and monitoring dashboards (Prometheus, Grafana, Alertmanager, kube-state-metrics) — deferred to v2
- Automated execution of the pre-event checklist
- Scheduled or automated backups
- Any new infrastructure provisioning beyond what Phases 1–5 deliver

## Assumptions

- The live cluster, CTFd platform, controller, and challenge pods are already deployed via Phases 1–5 before this phase is exercised.
- A test team account (team ID 999) exists in CTFd with known credentials, usable by the load test script.
- The `backups/` directory is writable on the host running the backup script; if missing, the script creates it.
- The organizer running the pre-event checklist has `kubectl` access to the cluster and `doctl` authenticated.
- The load test is run from a machine with network access to `ctfd.infodays.net`; no in-cluster execution required.
- The event-day runbook covers the 20–50 team scale as defined in the project plan (infrastructure specced for 50 worst case).

## Dependencies

- Phases 1–5 must all be complete and validated before Phase 6 deliverables can be exercised end-to-end.
- The load test tool (k6) must be installed on the machine running the load test.
- `kubectl` and a valid kubeconfig must be available on the machine running the backup script and checklist.
