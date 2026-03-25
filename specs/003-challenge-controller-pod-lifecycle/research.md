# Research: Challenge Controller & Pod Lifecycle

**Feature**: `003-challenge-controller-pod-lifecycle`
**Date**: 2026-03-24
**Status**: Complete

---

## R-001: Kubernetes Python Client — Deployment Patching

**Decision**: Use `AppsV1Api.patch_namespaced_deployment()` with a strategic merge patch body (dict). Set `replicas` via `spec.replicas`; set/clear annotations via `metadata.annotations`.

**Rationale**:
- The official `kubernetes` Python library mirrors the Kubernetes REST API. Strategic merge patch (the default when passing a dict) allows partial updates — only the fields in the body are modified; other fields are preserved.
- Setting `metadata.annotations["ctf/activated-at"]` to an ISO 8601 UTC string is a standard pattern; the annotation key must use a valid DNS subdomain prefix (`ctf/`).
- Clearing an annotation: setting the annotation value to `None` in a strategic merge patch (`{"metadata": {"annotations": {"ctf/activated-at": None}}}`) causes Kubernetes to delete the key. This is confirmed to work on DOKS (DigitalOcean Managed Kubernetes) with the K8s version used in this project (verified 2026-03-25 during live cluster testing). The alternative read-modify-write approach (read full annotations map, delete the key, patch the full map) would also work but was not required.
- The patch call signature: `apps_v1.patch_namespaced_deployment(name=..., namespace="challenges", body={...})`.

**Alternatives considered**:
- JSON Patch (`application/json-patch+json`): more verbose, requires specifying operation type (`add`, `remove`, `replace`); unnecessary for this use case.
- Replace (PUT via `replace_namespaced_deployment`): replaces the entire object — risks overwriting fields modified by K8s controllers between our read and write. Patch is always safer for partial updates.

---

## R-002: Kubernetes Python Client — Listing Deployments & Counting Active Pods

**Decision**: Use `AppsV1Api.list_namespaced_deployment(namespace="challenges", label_selector="team={id},managed-by=ctf-controller")` to retrieve all Deployments for a team, then filter in Python on `deploy.spec.replicas == 1` to count active instances.

**Rationale**:
- Kubernetes label selectors cannot filter on `spec.replicas` — that is not a label. The label selector narrows the list to the team's Deployments; the Python filter counts which ones are active.
- Counting via Deployment `spec.replicas` is more reliable than counting Pod phase (`Running`), because a Pod might be in `Pending` (image pull in progress) while `spec.replicas=1` correctly reflects intent.
- The 4-pod cap is an intent limit, not a physical Pod limit. Counting by `spec.replicas` aligns with the model.

**Alternatives considered**:
- Counting running Pods directly: flaky during scale-up (Pod not yet Running), and Pod churn (restarts) could temporarily give a wrong count.
- Storing active count in a ConfigMap: adds a separate state store that can drift from actual Deployment state; unnecessary when the Deployment spec is the ground truth.

---

## R-003: Annotation Format for `ctf/activated-at`

**Decision**: Store as a UTC ISO 8601 string (`2026-03-24T14:00:00Z`) in the annotation `ctf/activated-at`. Parse with `datetime.fromisoformat()` (Python 3.11+) comparing against `datetime.now(timezone.utc)`.

**Rationale**:
- Kubernetes annotations are string-typed. ISO 8601 UTC is human-readable, sortable, and unambiguous.
- Python 3.11+ `datetime.fromisoformat()` handles the `Z` suffix without a custom strptime format.
- Clearing the annotation (on deactivate or daemon expiry) requires patching `{"metadata": {"annotations": {"ctf/activated-at": None}}}`.
- The `/` in the annotation key (`ctf/activated-at`) is valid — the prefix `ctf` is treated as a namespace-like qualifier (any lowercase string is valid; it does not need to be a real DNS name for internal-only annotations).

**Alternatives considered**:
- Unix timestamp as string: harder to read in `kubectl describe`, harder to debug. ISO 8601 is preferred.
- Separate ConfigMap per team tracking activation times: fragile and adds a second source of truth for state the Deployment already knows.

---

## R-004: NGINX Ingress — TCP ConfigMap for `type=tcp` Challenges

**Decision**: Use the `tcp-services` ConfigMap in the `ingress-nginx` namespace. Each entry maps an external NodePort to an internal service: key = `"{external-port}"`, value = `"{namespace}/{service-name}:{target-port}"`. Bulk spawn adds entries via `CoreV1Api.patch_namespaced_config_map("tcp-services", "ingress-nginx", body={"data": {str(port): "challenges/svc-name:target"}})`.

**Rationale**:
- DOKS uses the Helm-installed NGINX Ingress Controller. TCP passthrough is configured via the `--tcp-services-configmap` arg (already set to `ingress-nginx/tcp-services` in the Helm values by default).
- Port pool starts at 30000 (above Kubernetes NodePort range default of 30000–32767). Ports are assigned sequentially from a pool at spawn time and stored in the ConfigMap as the single source of truth.
- The ConfigMap patch is a strategic merge patch — adding new keys does not remove existing entries.
- The resulting `nc team-3-pwn-1.challenges.infodays.net 30001` command is the instance URL for TCP challenges.

**Alternatives considered**:
- IngressRouteTCP (Traefik): prohibited by constitution (NGINX only).
- NodePort Services directly: requires knowing the node IP; load balancer IP is more stable and already managed by NGINX ingress.
- Storing port assignments in a separate database: overengineered; the ConfigMap is the correct K8s primitive for this.

---

## R-005: ThreadPoolExecutor for Parallel K8s Resource Creation

**Decision**: Use `concurrent.futures.ThreadPoolExecutor(max_workers=10)` with `executor.map()` or `submit()` + `as_completed()`. Wrap each creation call in a try-except; log errors per resource without stopping the overall spawn run.

**Rationale**:
- The `kubernetes` Python library uses synchronous HTTP (urllib3). Parallelism via threads is appropriate for I/O-bound work.
- `max_workers=10` is a reasonable concurrency for K8s API server throughput without triggering rate limiting. At 750 resources (50 teams × 15 challenges), 10 threads completes in ~75 serial-equivalent batches vs. 750 sequential calls.
- Per-resource exception handling ensures one failed resource (e.g., transient API error) does not abort the entire spawn run. The script prints `ERROR: team-3-web-sqli: {message}` and continues.
- `concurrent.futures.as_completed()` gives live progress reporting as futures complete.

**Alternatives considered**:
- `asyncio` with the async kubernetes client: would require rewriting all K8s calls as async; adds complexity to a CLI script. The sync client with threads is simpler.
- Serial execution: for 750 resources at ~100ms/call = 75 seconds. With 10 threads: ~7.5 seconds. Speed matters during pre-event setup.

---

## R-006: FastAPI Controller API Design

**Decision**: FastAPI 0.100+ with Pydantic v2 for request validation. `Depends(verify_controller_key)` for auth (timing-safe via `secrets.compare_digest`). `lifespan` context manager for startup validation of `CTF_MASTER_SECRET` and `CONTROLLER_KEY`. Single uvicorn worker (`workers=1`).

**Rationale**:
- Pydantic v2 validates request bodies at parse time; FastAPI maps validation errors to 422 responses. Custom exception classes (`ChallengeNotFound`, `MaxInstancesExceeded`) are caught by exception handlers that return 404 and 429 respectively.
- `Depends(verify_controller_key)` applies to all routes except `/health`, which must be reachable by K8s liveness probes without credentials.
- `lifespan` is the modern FastAPI startup pattern (replaces deprecated `on_event("startup")`). Raising during lifespan causes the container to exit with non-zero code, triggering K8s CrashLoopBackOff — a deliberate fail-fast mechanism.
- K8s client init: `load_incluster_config()` first (try-except), fallback to `load_kube_config()` for local development. Client stored in `app.state`.
- Single worker is correct for this CPU/RAM budget (0.25 CPU / 256 Mi) and async workload. Horizontal scaling via K8s replicas is preferred over in-process multi-worker.

**Alternatives considered**: See R-003 in FastAPI research (Depends vs middleware, lifespan vs on_event).

---

## R-007: CTFd Plugin Architecture

**Decision**: Plugin lives at `CTFd/plugins/controller-plugin/` with `__init__.py` exporting `load(app: Flask)`. UI injection via a JS file served from `assets/` (Blueprint static folder), loaded via a `<script>` tag injected into every HTML response by a Flask `after_request` hook. Controller URL, key, and team ID are injected as `window.CTF_CONTROLLER = {team_id, url, key}`. Controller URL and key stored in `CTFd.models.Configs`.

**Rationale**:
- Standard CTFd plugin structure: `CTFd/plugins/{name}/__init__.py` with `load(app)`. Blueprint with `static_folder='assets'` serves JS at `/plugins/controller-plugin/assets/`.
- JS-based DOM injection is less invasive than template overrides: the plugin does not copy or modify CTFd core templates, which makes it resilient to CTFd version upgrades.
- **Jinja2 globals do NOT work** for this use case: CTFd uses AJAX-loaded modals for challenge display — there is no per-challenge template render where a global would be called. The `after_request` hook injects a `<script>window.CTF_CONTROLLER={...}</script>` block before `</body>` on every HTML page, making config available to the JS regardless of how the challenge UI is loaded.
- `current_user.team_id` is read in the `after_request` hook from CTFd's `current_user` object and embedded in the injected config script.
- `CTFd.models.Configs` entries allow runtime-editable configuration in the admin panel without pod restarts. Defaults (`CONTROLLER_URL`, `X_CONTROLLER_KEY` = `"CHANGE_ME"`) are set on first load if missing. The admin must update `X_CONTROLLER_KEY` in the CTFd admin panel to match the value in the `controller-key` K8s Secret.
- Plugin does NOT touch flag validation or scoring — all CTFd challenge types except `web/pwn/misc` (service challenges) are unaffected.
- **Challenge ID resolution**: The JS plugin derives the manifest `challenge_id` by slugifying the CTFd challenge name (lowercase, spaces → hyphens, strip non-alphanumeric). This means CTFd challenge names MUST match the manifest `id` field when slugified (e.g., CTFd name `"web-sqli"` → slug `"web-sqli"` = manifest id `"web-sqli"`). Challenge names should be set to exactly match the manifest ID at import time.

**Alternatives considered**:
- Template override (`challenges/challenge.html` copy): fragile, breaks on CTFd version update.
- CTFd challenge attempt event hook: fires post-submission, not relevant for UI state display.
- Hardcoded controller URL: unacceptable; must be runtime-configurable.

---

## R-008: Flag Derivation

**Decision**: `HMAC-SHA256(CTF_MASTER_SECRET.encode(), f"{team_id}:{challenge_id}".encode()).hexdigest()[:32]` formatted as `infodays{<hex>}`. Read `CTF_MASTER_SECRET` from `os.environ["CTF_MASTER_SECRET"]`; raise `ValueError` at startup if unset.

**Rationale**:
- Mandated by constitution Principle I. No other flag derivation method is permitted.
- Python's `hmac.new(key, msg, digestmod='sha256').hexdigest()` produces a 64-char hex string; `[:32]` truncates to 32 hex chars (128-bit security).
- The flag is derived at spawn time, stored in a K8s Secret per (team, challenge), and injected as env var `FLAG` at pod runtime. It is NEVER stored in source files or logs.

---

## R-009: Local Development Environment

**Decision**: k3d (per constitution). Script: `k3d cluster create infodays-dev --agents 2`. The controller runs via `python api.py` with `KUBECONFIG` pointing to the k3d cluster. The daemon runs separately with the same config.

**Rationale**:
- Constitution mandates k3d; minikube, kind, and Vagrant are prohibited.
- k3d creates a lightweight K8s cluster in Docker containers. It supports NGINX Ingress via Helm (same as DOKS).
- For test runs, test resources use `team_id=999` and challenge IDs prefixed `test-` per naming conventions.

**Alternatives considered**: None — k3d is mandated.

---

## Resolved NEEDS CLARIFICATION

| Item | Resolution |
|------|-----------|
| Activation 4-pod cap counting method | Count `spec.replicas == 1` on Deployments labeled `team={id}` — not Pod phase |
| Re-activation after daemon suspend | Permitted immediately; no cooldown |
| Missing `CTF_MASTER_SECRET` at startup | Controller fails to start with `ValueError`; pod enters CrashLoopBackOff |
| TCP port assignment (static vs dynamic) | Dynamic from pool at spawn time; stored in NGINX TCP ConfigMap; stable across re-runs if manifest order is stable |
| NGINX TCP ConfigMap name | `tcp-services` in namespace `ingress-nginx` |
| CTFd plugin `current_user.team_id` access | Via Flask `after_request` hook reading `current_user.team_id`; embedded as `window.CTF_CONTROLLER.team_id` in page (Jinja2 globals do not work — CTFd uses AJAX modals) |
