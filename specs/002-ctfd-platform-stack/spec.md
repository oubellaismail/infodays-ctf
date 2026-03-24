# Feature Specification: CTFd Platform Stack

**Feature Branch**: `002-ctfd-platform-stack`
**Created**: 2026-03-24
**Status**: Draft
**Input**: User description: "Deploy CTFd platform stack with MySQL, Redis, ingress, network policies, and admin scripts for the InfoDays CTF event"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Contestants Access the CTF Platform (Priority: P1)

Invited teams visit the CTFd competition platform and can log in, view challenges, and submit flags. The platform is accessible over a secure HTTPS connection at the expected URL and responds reliably for all 50 teams throughout the 12-hour event.

**Why this priority**: Without a working, accessible platform, the entire event cannot proceed. All other features depend on this.

**Independent Test**: Can be fully tested by visiting `https://ctfd.infodays.net` from an external browser, logging in with a pre-created team account, and verifying the platform responds to flag submissions.

**Acceptance Scenarios**:

1. **Given** the CTFd stack is deployed, **When** a contestant visits `https://ctfd.infodays.net`, **Then** a valid HTTPS connection is established with a trusted TLS certificate and the CTFd login page is displayed.
2. **Given** a pre-created team account exists, **When** a contestant logs in, **Then** they see the challenge board and can navigate the platform.
3. **Given** 50 teams are simultaneously active, **When** contestants browse and submit flags, **Then** the platform remains responsive without errors.
4. **Given** the platform is running, **When** a contestant attempts to self-register, **Then** registration is rejected — only pre-created accounts can log in.

---

### User Story 2 — Admin Deploys and Configures the Platform (Priority: P2)

The event admin applies the infrastructure configuration, and CTFd automatically initialises with the correct event settings: team mode enabled, public registration disabled, and the flag format `infodays{...}` active. No manual post-deploy configuration steps are needed.

**Why this priority**: Correct event configuration must be locked in before teams are imported. A misconfigured platform (e.g., open registration) would compromise event integrity.

**Independent Test**: Can be fully tested by deploying the stack and running the setup script, then verifying via the CTFd admin panel that team mode, registration, and flag format settings match the required values.

**Acceptance Scenarios**:

1. **Given** the stack is deployed, **When** the admin runs the setup script, **Then** CTFd is configured with: event name "InfoDays CTF", team mode on, registration disabled, and flag format `infodays{...}`.
2. **Given** CTFd is configured, **When** an unauthenticated user attempts to register, **Then** the registration form is absent or blocked.
3. **Given** the setup script targets a CTFd instance that is not yet ready, **When** the script runs, **Then** it waits and retries until CTFd is available rather than failing immediately.

---

### User Story 3 — Admin Imports Team Accounts (Priority: P3)

Before the event starts, the admin runs an import script against a CSV file of team names, emails, and passwords. The script creates all team accounts in CTFd, reports a clear summary of outcomes, and is safe to re-run without creating duplicates.

**Why this priority**: All 20–50 team accounts must exist before the event opens; this script is the mechanism for bulk creation.

**Independent Test**: Can be fully tested by providing a CSV with 5 test teams, running the import script, then verifying through the CTFd admin panel that exactly 5 teams exist with the correct credentials.

**Acceptance Scenarios**:

1. **Given** a `teams.csv` with valid team entries, **When** the import script runs, **Then** all teams are created in CTFd and the script prints a summary showing counts of created, skipped (already exists), and failed entries.
2. **Given** some teams already exist from a previous run, **When** the import script is run again with the same CSV, **Then** no duplicate teams are created and existing entries are reported as "already exists".
3. **Given** a team entry is malformed, **When** the import script encounters it, **Then** that entry is reported as failed without stopping the import of other entries.

---

### User Story 4 — Data Survives Pod Restarts (Priority: P4)

Competitor progress, flag submissions, and scores are not lost if CTFd pods are restarted or rescheduled during the event. The database layer persists all state to durable storage.

**Why this priority**: Data loss during the event would damage competitor trust and require manual remediation.

**Independent Test**: Can be tested by submitting a flag, restarting the CTFd deployment pods, then verifying the submission still appears in the platform.

**Acceptance Scenarios**:

1. **Given** a flag submission has been recorded, **When** all CTFd pods are restarted, **Then** the submission is still present after the pods recover.
2. **Given** the database pod is restarted, **When** it comes back online, **Then** all previously stored data is intact and CTFd reconnects automatically.

---

### User Story 5 — Network Isolation Protects the Event (Priority: P5)

The CTFd platform components can only communicate with each other (database and cache) and cannot reach the challenge namespace or any external service not required for operation. This prevents a compromised or misconfigured component from interfering with challenge pods.

**Why this priority**: Network isolation is a security baseline for the event. Breaches here could allow cross-team interference or challenge flag leakage.

**Independent Test**: Can be tested by attempting to make a network request from within a CTFd pod to a pod in the challenges namespace and confirming the connection is blocked.

**Acceptance Scenarios**:

1. **Given** the network policies are applied, **When** a CTFd pod attempts to reach any pod in the `challenges` namespace, **Then** the connection is blocked.
2. **Given** the network policies are applied, **When** CTFd accesses the database and cache, **Then** those connections succeed normally.
3. **Given** the network policies are applied, **When** an external request reaches `ctfd.infodays.net`, **Then** it is routed to CTFd through the ingress and no direct access to MySQL or Redis is possible from outside the cluster.

---

### Edge Cases

- What happens when CTFd pods restart during active flag submissions? Persistent database ensures no submissions are lost; in-flight requests may fail but can be resubmitted.
- How does the platform behave if the database is temporarily unavailable at startup? CTFd waits for the database to be reachable before starting; it will not serve traffic until the dependency is ready.
- What if the import CSV contains duplicate team names? The script detects existing teams and reports them as "already exists" without creating duplicates.
- What if the TLS certificate cannot be issued at deploy time? The platform is unavailable over HTTPS until the certificate is provisioned; the certificate authority retries automatically.
- What if a CTFd pod is rescheduled mid-event? Two replicas ensure the remaining pod continues handling requests while the rescheduled pod recovers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The platform MUST be accessible at `https://ctfd.infodays.net` with a valid, browser-trusted TLS certificate.
- **FR-002**: CTFd MUST run with two replicas to provide continuity during pod rescheduling.
- **FR-003**: CTFd MUST be configured with team mode enabled, public registration disabled, and flag format `infodays{...}`.
- **FR-004**: All CTFd configuration MUST be supplied via environment variables — no configuration values baked into container images.
- **FR-005**: The database MUST store its data on persistent block storage so that data survives pod restarts and rescheduling.
- **FR-006**: Redis MUST serve as the session and cache backend for CTFd; Redis data does not need to persist across restarts.
- **FR-007**: All inter-component credentials (database passwords, application secret key, mail credentials) MUST be stored in a managed secret and never in source-controlled files containing real values.
- **FR-008**: CTFd pods MUST wait for the database to be reachable before starting.
- **FR-009**: The platform MUST expose health check endpoints; pods that fail health checks MUST be automatically removed from load balancing.
- **FR-010**: All services (CTFd, database, cache) MUST be reachable only within the cluster — no direct external exposure except through the ingress.
- **FR-011**: Network policy MUST prevent CTFd pods from reaching any pods outside the `ctfd` namespace, except as explicitly permitted (ingress controller inbound, database and cache outbound).
- **FR-012**: The setup script MUST configure CTFd via its admin API and MUST wait for the platform to be ready before attempting configuration.
- **FR-013**: The team import script MUST accept a CSV file (columns: team_name, email, password) and create team accounts.
- **FR-014**: The team import script MUST be idempotent — re-running it against an already-imported CSV MUST NOT create duplicate teams.
- **FR-015**: The team import script MUST print a summary of created, skipped, and failed entries after completion.
- **FR-016**: A CSV template with the required column structure MUST be provided as a starting point for the admin.

### Key Entities

- **CTFd Application**: The competition platform serving the challenge board, flag submissions, and scoreboard to contestants. Stateless — all persistent state delegated to the database.
- **Database**: Persistent storage for all CTFd data including teams, challenges, submissions, and scores. Single replica backed by durable block storage.
- **Cache**: Ephemeral session and caching layer for CTFd. No persistence required.
- **Team Account**: A CTFd team record containing team name, login email, and password. Shared by up to 4 players. Created by the admin before the event via the import script.
- **Credential Store**: Holds all sensitive credentials used by CTFd, the database, and reserved keys for future components. Provided as a template in source control; real values injected at deploy time and never committed.
- **Ingress Rule**: Routes external HTTPS traffic at `ctfd.infodays.net` to the CTFd service, with TLS termination handled automatically.
- **Network Policy**: Declares which pods may communicate with which, enforcing that CTFd can reach only the database and cache, and that no external party can bypass the ingress.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: CTFd is reachable at `https://ctfd.infodays.net` with a valid TLS certificate within 10 minutes of completing the deployment.
- **SC-002**: All 50 teams can log in and view the challenge board simultaneously without errors or timeouts.
- **SC-003**: Flag submissions are recorded and reflected on the scoreboard within 5 seconds under normal load.
- **SC-004**: After restarting all CTFd pods, the platform is fully operational again within 60 seconds and all previously submitted flags remain visible.
- **SC-005**: The team import script successfully creates 5 test teams in under 30 seconds with a clear summary output.
- **SC-006**: Re-running the import script against the same CSV produces zero new teams and reports all entries as "already exists".
- **SC-007**: A network connection attempt from within a CTFd pod to any pod in the challenges namespace is blocked without exception.
- **SC-008**: The setup script completes CTFd configuration with zero manual steps required in the CTFd admin UI.

## Assumptions

- The `ctfd` namespace already exists in the cluster (provisioned in Phase 1).
- The ingress controller and certificate manager with the `letsencrypt-prod` issuer are already running (Phase 1 deliverable).
- The `infodays.net` domain DNS is configured to point to the cluster load balancer.
- Persistent block storage is available as a provisioned storage class on the cluster.
- Mail configuration (SMTP credentials) will be provided at deploy time; if not provided, email features will be non-functional but the platform will still operate.
- The `CTF_MASTER_SECRET` credential in the secret store is reserved for the Phase 3 controller and is not used by Phase 2 components.
- Resource limits (512 Mi RAM / 0.5 CPU for CTFd, 1 Gi / 0.5 CPU for database, 256 Mi / 0.1 CPU for cache) are appropriate for the expected 50-team load and may be adjusted based on observed usage.
- The event duration is 12 hours; data retention beyond the event is out of scope for this phase.
