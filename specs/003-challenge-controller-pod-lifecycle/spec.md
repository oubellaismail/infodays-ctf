# Feature Specification: Challenge Controller & Pod Lifecycle

**Feature Branch**: `003-challenge-controller-pod-lifecycle`
**Created**: 2026-03-24
**Status**: Draft
**Input**: Phase 3 — Challenge Controller & Pod Lifecycle (derived from `.specify/Plan.md`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Admin Pre-Spawns All Challenge Pods Before the Event (Priority: P1)

Before the event starts, the admin runs a bulk-spawn script that reads the list
of teams from CTFd and the challenge manifests from the repository. The script
creates every (team, service-challenge) combination as a suspended Kubernetes
Deployment (replicas=0), a per-team flag Secret, and a Service in the
`challenges` namespace. The operation is safe to re-run without creating
duplicates.

**Why this priority**: No team can activate a challenge unless its Deployment
already exists. The pre-spawn step is the prerequisite for every player-facing
interaction.

**Independent Test**: Run `bulk_spawn.py` targeting 5 test teams (team_id
prefixed `test-`) × 3 test challenges (ids prefixed `test-`). Verify via
`kubectl` that exactly 15 Deployments, 15 Secrets, and 15 Services exist with
`replicas=0`, correct labels, and empty `ctf/activated-at` annotations. Re-run
the script and confirm no duplicate resources are created.

**Acceptance Scenarios**:

1. **Given** a list of 5 test teams and 3 service-challenge manifests,
   **When** `bulk_spawn.py` runs,
   **Then** 15 Deployments, 15 Secrets, and 15 Services exist in the
   `challenges` namespace, each with `replicas=0` and labels
   `team={id}`, `challenge={id}`, `managed-by=ctf-controller`.

2. **Given** the resources already exist from a previous run,
   **When** `bulk_spawn.py` runs again with the same inputs,
   **Then** no new resources are created and the script reports "Skipped
   (exists)" for each one.

3. **Given** a challenge manifest with `type=http`,
   **When** `bulk_spawn.py` processes it,
   **Then** an Ingress rule is created pointing to
   `team-{id}-{challenge-id}.challenges.infodays.net`.

4. **Given** a challenge manifest with `type=tcp`,
   **When** `bulk_spawn.py` processes it,
   **Then** a unique port (≥ 30000) is assigned and the NGINX TCP ConfigMap
   entry is created.

5. **Given** a challenge with `type: static`,
   **When** `bulk_spawn.py` encounters it,
   **Then** no Deployment, Secret, or Service is created — it is silently skipped.
   Static challenges (forensics, crypto, etc.) have no running service; flags are
   derived per-team and players download a zip from the plugin's `/download/{id}` endpoint.

---

### User Story 2 — Team Activates a Challenge Instance (Priority: P1)

A team clicks "▶ Start Instance" on a challenge page in CTFd. The CTFd plugin
calls the controller `/activate` endpoint, the Deployment scales to
`replicas=1`, and the plugin displays the instance URL (HTTP) or `nc` command
(TCP) within seconds.

**Why this priority**: Starting a challenge instance is the primary player
action the controller exists to support. All other controller features exist to
support or constrain this.

**Independent Test**: With a pre-spawned Deployment at `replicas=0`, call
`POST /activate` with a valid `team_id` and `challenge_id`. Verify the
Deployment reaches `replicas=1`, the annotation `ctf/activated-at` is set to
approximately the current timestamp, and the response body contains `status:
"starting"` and a non-empty `url`.

**Acceptance Scenarios**:

1. **Given** a pre-spawned Deployment at `replicas=0`,
   **When** `POST /activate` is called with valid `team_id` and `challenge_id`,
   **Then** the Deployment is patched to `replicas=1`, `ctf/activated-at` is
   set to the current ISO timestamp, and the response is
   `200 { status: "starting", url: "..." }`. The plugin MUST display the URL
   immediately alongside a note "Instance is starting, may take ~30 seconds"
   — it MUST NOT wait for pod readiness before revealing the URL.

2. **Given** a team already has 4 Deployments at `replicas=1`,
   **When** `POST /activate` is called for a 5th challenge,
   **Then** the response is `429 { error: "Max 4 active instances reached.
   Stop one to continue." }` and no Deployment is modified.

3. **Given** an unknown `team_id` or `challenge_id`,
   **When** `POST /activate` is called,
   **Then** the response is `404 { error: "Challenge not found" }`.

4. **Given** a request without the `X-Controller-Key` header, or with an
   invalid key,
   **When** any API endpoint is called,
   **Then** the response is `401 { error: "Unauthorized" }`.

---

### User Story 3 — Team Deactivates a Challenge Instance (Priority: P2)

A team clicks "⏹ Stop Instance" to free up one of their four active slots.
The controller scales the Deployment to `replicas=0` and clears the
`ctf/activated-at` annotation. The plugin immediately reflects the new
"Suspended" status.

**Why this priority**: Releasing a slot is required before a team can start
a fifth challenge. Without this, the 4-pod cap would permanently lock teams
out of additional challenges.

**Independent Test**: Scale a Deployment to `replicas=1` and set
`ctf/activated-at`. Call `POST /deactivate`. Verify `replicas=0` and
annotation is cleared. Then call `POST /activate` again — verify it succeeds
(slot freed).

**Acceptance Scenarios**:

1. **Given** a running Deployment (`replicas=1`),
   **When** `POST /deactivate` is called,
   **Then** the Deployment is patched to `replicas=0`, `ctf/activated-at` is
   cleared, and the response is `200 { status: "suspended" }`.

2. **Given** a Deployment already at `replicas=0`,
   **When** `POST /deactivate` is called,
   **Then** the response is `200 { status: "suspended" }` and no error is
   raised — idempotent.

---

### User Story 4 — Lifetime Daemon Enforces the 60-Minute Timeout (Priority: P2)

Running pods are automatically suspended after 60 minutes from the value of
their `ctf/activated-at` annotation. A daemon process polls all managed
Deployments every 5 minutes and scales any expired ones to `replicas=0`. Teams
can re-activate immediately after suspension.

**Why this priority**: Without automated expiry, teams could monopolise
cluster resources by leaving instances running indefinitely. Enforcing lifetime
ensures fair resource distribution over the 12-hour event.

**Independent Test**: Set `ctf/activated-at` to a timestamp 61 minutes in the
past on a running Deployment. Run one daemon iteration. Verify the Deployment
is patched to `replicas=0` and `ctf/activated-at` is cleared.

**Acceptance Scenarios**:

1. **Given** a Deployment at `replicas=1` with `ctf/activated-at` set to 61
   minutes ago,
   **When** the daemon performs its reconciliation loop,
   **Then** the Deployment is patched to `replicas=0` and `ctf/activated-at`
   is cleared. A log line is emitted:
   `"Auto-suspended team-{id}-{challenge-id} (lifetime exceeded)"`.

2. **Given** a Deployment at `replicas=1` with `ctf/activated-at` set to 30
   minutes ago,
   **When** the daemon performs its reconciliation loop,
   **Then** the Deployment is NOT patched — lifetime has not expired.

3. **Given** a Deployment at `replicas=0` (regardless of annotation),
   **When** the daemon performs its reconciliation loop,
   **Then** the Deployment is NOT modified.

4. **Given** a pod was suspended by the daemon,
   **When** `POST /activate` is called for the same challenge,
   **Then** the pod is re-activated (`replicas=1`, fresh `ctf/activated-at`)
   immediately — re-activation after timeout is permitted.

5. **Given** the daemon is running,
   **When** it completes one full reconciliation pass,
   **Then** it sleeps exactly 5 minutes before starting the next pass.

---

### User Story 5 — CTFd Plugin Shows Real-Time Instance Status (Priority: P3)

On any web, pwn, or misc challenge page in CTFd, the plugin shows the team's
current instance status (Fresh / Suspended / Running), a Start or Stop button,
and — when Running — the instance URL or `nc` command. The status is refreshed
every 15 seconds via a background fetch.

**Why this priority**: The plugin is the only user interface to the controller.
Without it, teams have no way to start, stop, or discover the address of their
instances.

**Independent Test**: Visit a challenge page as a logged-in team. Confirm the
status badge appears, the Start button is present when status is Fresh, and
clicking it updates the badge to Running and reveals the instance URL within a
few seconds. Confirm the Stop button is present when Running.

**Acceptance Scenarios**:

1. **Given** a challenge with status `fresh` (replicas=0, never activated),
   **When** the challenge page is loaded,
   **Then** a "Fresh" grey badge and a "▶ Start Instance" button are shown.
   No instance URL is shown.

2. **Given** a challenge with status `running` (replicas=1),
   **When** the challenge page is loaded,
   **Then** a "Running" green badge, a "⏹ Stop Instance" button, and the
   instance URL (or `nc` command) are shown.

3. **Given** a challenge with status `suspended` (replicas=0, previously
   activated),
   **When** the challenge page is loaded,
   **Then** a "Suspended" grey badge and a "▶ Start Instance" button are
   shown.

4. **Given** a running instance,
   **When** 15 seconds elapse with no user interaction,
   **Then** the status badge and button are refreshed via a background fetch
   to `GET /status/{team_id}`.

5. **Given** the background fetch to `GET /status/{team_id}` fails (network
   error, controller unreachable, or non-200 response),
   **When** the error occurs,
   **Then** the badge shows "Unknown" (grey), the Start/Stop button is
   disabled, a "Retry" link is rendered, and the error is logged to the
   browser console. No stale status is silently preserved.

6. **Given** the challenge has `type: static` (no running service),
   **When** the challenge page is loaded,
   **Then** the plugin shows a "Download Challenge" button instead of Start/Stop controls.
   The button calls the plugin's `/download/{challenge_id}` endpoint which generates
   a per-team zip on the fly containing the challenge files and the team's HMAC flag.

---

### User Story 6 — Admin Imports Derived Flags into CTFd (Priority: P3)

Before the event starts, the admin runs `import_flags.py` to push a derived
flag for every (team, service-challenge) pair into CTFd via the admin API.
Each flag is bound to the correct team and challenge. The script is safe to
re-run.

**Why this priority**: CTFd must know each team's unique flag before the event
begins so that flag submission validation works correctly.

**Independent Test**: Run `import_flags.py` for 5 test teams × 3 test
challenges. Verify via the CTFd admin panel that 15 flag entries exist, each
matching `derive_flag(team_id, challenge_id)`.

**Acceptance Scenarios**:

1. **Given** 5 test teams and 3 service-challenge manifests,
   **When** `import_flags.py` runs,
   **Then** 15 flag entries exist in CTFd, each matching
   `infodays{ HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32] }`.

2. **Given** flags already exist from a prior run,
   **When** `import_flags.py` runs again,
   **Then** no duplicate flags are created and existing entries are skipped.

---

### Edge Cases

- **Controller pod restart mid-event**: The controller is stateless — it reads
  live Deployment state from Kubernetes on every request. A pod restart does
  not cause data loss or inconsistent state.
- **Daemon restarts**: Because lifetime state is stored in the
  `ctf/activated-at` annotation on the Deployment (not in daemon memory), a
  daemon restart does not reset or lose any lifetime information.
- **Activation of an already-running pod**: `/activate` on a Deployment
  already at `replicas=1` is treated as a no-op (idempotent) — the 4-pod cap
  count must not double-count it.
- **Team_id not found in K8s**: `/activate` and `/deactivate` MUST return 404,
  never 500 — error handling must distinguish "not found" from unexpected
  failures.
- **bulk_spawn.py running while event is live**: Because it is idempotent and
  only creates resources at `replicas=0`, running it during the event is safe.
  Existing running pods are not affected.
- **Concurrent activation requests**: Two simultaneous `/activate` requests
  from the same team could both pass the 4-pod cap check before either writes.
  The controller performs the cap check and patch as two separate K8s API
  calls — eventual over-cap is acceptable (tolerance of ≤ 1 extra pod), not a
  security concern.
- **CTFd plugin with no team session**: If a visitor has no CTFd team session,
  the plugin must degrade gracefully — no error thrown, no broken UI.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Flags MUST be derived exclusively via
  `HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32]` and
  formatted as `infodays{<hex>}`. No other derivation method is permitted.
- **FR-002**: `CTF_MASTER_SECRET` MUST be read from the environment variable
  sourced from K8s Secret `ctfd-secrets`. It MUST NOT be hardcoded or appear
  in any source file.
- **FR-003**: `bulk_spawn.py` MUST create Deployments, Secrets, Services, and
  Ingress/TCP entries for all (team, service-challenge) combinations in the
  `challenges` namespace before the event starts.
- **FR-004**: All spawned Deployments MUST start at `replicas=0` with empty
  `ctf/activated-at` annotations.
- **FR-005**: All spawned resources MUST carry labels `team={id}`,
  `challenge={id}`, `managed-by=ctf-controller`.
- **FR-006**: `bulk_spawn.py` MUST be idempotent — re-running against existing
  resources produces no errors and no duplicate objects. For TCP challenges,
  the script MUST read the existing NGINX TCP ConfigMap before assigning
  ports: existing port→service mappings are preserved; new ports are assigned
  only to services not yet in the ConfigMap.
- **FR-007**: `POST /activate` MUST reject a 5th activation for the same team
  with HTTP 429 and the message `"Max 4 active instances reached. Stop one to
  continue."`.
- **FR-008**: `POST /activate` MUST set `ctf/activated-at` to the current UTC
  ISO 8601 timestamp on the Deployment annotation.
- **FR-009**: `POST /deactivate` MUST set `replicas=0` and clear
  `ctf/activated-at`.
- **FR-010**: The lifetime daemon MUST scale any Deployment to `replicas=0`
  and clear `ctf/activated-at` when
  `(now − ctf/activated-at) > 60 minutes`. It MUST NEVER delete Deployments.
- **FR-011**: The lifetime daemon MUST run its reconciliation loop every 5
  minutes.
- **FR-012**: All controller API endpoints MUST require the `X-Controller-Key`
  header. Requests with a missing or invalid key MUST return HTTP 401.
- **FR-013**: `GET /status/{team_id}` MUST return the status (`running`,
  `suspended`, `fresh`, or `unknown`) and instance URL for every challenge
  belonging to the team. If no Deployments exist for the given `team_id`
  (e.g., bulk_spawn has not run), the response MUST be
  `200 { "challenges": [] }` — never 404.
- **FR-014**: The CTFd plugin MUST show status badge and Start/Stop buttons
  only for service challenge categories (`web`, `pwn`, `misc`). File-based
  categories MUST be unaffected.
- **FR-015**: The CTFd plugin MUST auto-refresh status every 15 seconds via
  `GET /status/{team_id}`. If the fetch fails (network error or non-200
  response), the badge MUST show "Unknown" with a disabled button and a
  "Retry" link; the error MUST be logged to the browser console. Stale
  status MUST NOT be silently preserved across a failed fetch.
- **FR-016**: `import_flags.py` MUST post each derived flag to CTFd via the
  admin API, associated with the correct team and challenge. It MUST be
  idempotent.
- **FR-017**: `teardown-challenges.sh` MUST delete all resources labelled
  `managed-by=ctf-controller` in the `challenges` namespace. It MUST prompt
  for confirmation before executing.
- **FR-018**: Naming MUST follow the convention:
  Deployment/Pod `team-{team_id}-{challenge_id}`,
  Secret `team-{team_id}-{challenge_id}-secret`,
  Service `team-{team_id}-{challenge_id}-svc`.
- **FR-019**: Test resources MUST use `team_id=999` and challenge IDs prefixed
  with `test-`.
- **FR-020**: The controller API Deployment MUST run at `replicas=2`. It is
  stateless — both replicas read/write K8s directly with no shared in-process
  state.

### Key Entities

- **Challenge Manifest**: YAML file describing a single challenge; fields:
  `id`, `name`, `category`, `image`, `port`, `type` (`http`|`tcp`), `points`,
  `memory_limit` (optional).
- **Derived Flag**: The per-team flag string for a service challenge; computed
  at spawn time and stored in a K8s Secret.
- **Managed Deployment**: A Kubernetes Deployment in the `challenges`
  namespace created by `bulk_spawn.py`; carries the `ctf/activated-at`
  annotation and `managed-by=ctf-controller` label.
- **Activation Record**: The state held in the `ctf/activated-at` annotation
  on a Deployment; set on `/activate`, cleared on `/deactivate` or daemon
  expiry.
- **Controller API**: The FastAPI service running in the `ctfd` namespace that
  the CTFd plugin calls; exposes `/activate`, `/deactivate`,
  `/status/{team_id}`, `/health`. Runs at **8 replicas** (stateless,
  active-active; IO-bound on K8s API calls; validated at 200 VU load with 0% errors).
- **Lifetime Daemon**: A separate lightweight Deployment in the `ctfd`
  namespace that polls managed Deployments every 5 minutes and enforces the
  60-minute lifetime.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `bulk_spawn.py` creates all K8s resources for 5 test teams × 3
  test service challenges — zero errors, all at `replicas=0`, idempotent on
  re-run.
- **SC-002**: `POST /activate` scales the target Deployment to `replicas=1`
  and sets `ctf/activated-at` within 2 seconds of the request.
- **SC-003**: `POST /activate` returns HTTP 429 when a team already has 4
  running instances — 100% of such requests are rejected.
- **SC-004**: `POST /deactivate` scales the target Deployment to `replicas=0`
  and clears `ctf/activated-at` within 2 seconds.
- **SC-005**: The lifetime daemon scales a Deployment to `replicas=0` within
  one 5-minute polling interval after the 60-minute lifetime is exceeded
  (max latency: 5 minutes post-expiry).
- **SC-006**: Re-activation after daemon-imposed suspension works immediately
  — `POST /activate` succeeds and the pod reaches `replicas=1`.
- **SC-007**: The CTFd plugin displays the correct status badge and
  Start/Stop button on a test challenge page without console errors.
- **SC-008**: `import_flags.py` pushes all derived flags for 5 test teams × 3
  challenges to CTFd API — zero errors, verified via admin panel.
- **SC-009**: All API calls with a missing or invalid `X-Controller-Key`
  return HTTP 401.
- **SC-010**: `teardown-challenges.sh` deletes all managed resources in the
  `challenges` namespace after confirmation — verified via `kubectl get all
  -n challenges`.

---

## Clarifications

### Session 2026-03-24

- Q: When the plugin's background status fetch fails (controller unreachable or non-200), what should the badge and buttons show? → A: Show "Unknown" badge + disabled button + "Retry" link; log the error to the browser console. Stale status must not be silently preserved.
- Q: After clicking Start, should the instance URL be shown immediately (even before the pod is Ready) or only after the pod is accepting connections? → A: Show URL immediately after `/activate` returns, alongside a note "Instance is starting, may take ~30 seconds". No readiness polling required.
- Q: Should the controller API run at 1 or 2 replicas? → A: Started at 2 replicas; scaled to 8 under 200-VU load testing (50 teams × 4 players). IO-bound FastAPI benefits from more replicas with 8 uvicorn workers each.
- Q: What should `GET /status/{team_id}` return when the team has no Deployments (e.g., bulk_spawn not yet run)? → A: `200 { "challenges": [] }` — empty list, never 404.
- Q: When `bulk_spawn.py` is re-run and a TCP port for a service already exists in the NGINX ConfigMap, what should it do? → A: Read ConfigMap first; skip ports already assigned to any service; assign new ports only to new services (preserves live assignments across re-runs).
- Q: How is the 4-pod cap counted — by Deployment replicas or by running Pod
  count? → A: By Deployment label query (`replicas=1` count via K8s API on
  Deployments labeled `team={id}` in the `challenges` namespace). Pod phase
  is not checked.
- Q: Can a team re-activate a challenge immediately after the daemon suspends
  it, or is there a cooldown? → A: Re-activation is permitted immediately —
  no cooldown.
- Q: What happens if `CTF_MASTER_SECRET` is not set in the environment?
  → A: The controller MUST fail to start with a clear error message. It MUST
  NOT silently derive flags using an empty or default secret.
- Q: Are TCP challenges assigned ports statically (in manifest) or dynamically
  at spawn time? → A: Assigned from a pool at spawn time; the assignment is
  stored in the NGINX TCP ConfigMap and reflected in the instance URL returned
  by `/activate`.

---

## Assumptions

- All service-challenge images are already present in DOCR before
  `bulk_spawn.py` runs (Phase 4 prerequisite).
- `CTF_MASTER_SECRET` is pre-created in K8s Secret `ctfd-secrets` in the
  `ctfd` namespace before any controller component starts.
- `X-Controller-Key` is pre-created as a separate K8s Secret and mounted into
  both the controller API pod and the CTFd plugin configuration before the
  event.
- The `challenges` namespace already exists with the `restricted`
  PodSecurityStandard and default-deny NetworkPolicy (Phase 1 prerequisite).
- The CTFd instance is already running and the admin API token is available
  before `import_flags.py` runs.
- TCP port pool starts at 30000. On each run, `bulk_spawn.py` MUST read the
  existing NGINX TCP ConfigMap before assigning ports; any port already mapped
  to a service is skipped. New ports are assigned only to services not yet
  present in the ConfigMap. This preserves live port assignments across
  re-runs and prevents collisions.
- The controller and daemon run with dedicated ServiceAccounts that have
  scoped RBAC permissions. `k8s/rbac/challenge-controller-rbac.yaml` defines:
  - `ServiceAccount: ctf-controller` in the `ctfd` namespace
  - `Role: ctf-controller` in `challenges` namespace (`get, list, watch, create, update, patch` on Deployments, Secrets, Services, Ingresses — no `delete`; teardown uses admin kubeconfig)
  - `Role: ctf-controller-nginx` in `ingress-nginx` namespace (`get, patch` on ConfigMaps, for `tcp-services`)
  - Two `RoleBindings` connecting the ServiceAccount to each Role
  (Originally deferred to Phase 5 — delivered in Phase 3.)
