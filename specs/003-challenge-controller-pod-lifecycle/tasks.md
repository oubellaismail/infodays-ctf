# Tasks: Challenge Controller & Pod Lifecycle

**Feature branch**: `003-challenge-controller-pod-lifecycle`
**Input**: `specs/003-challenge-controller-pod-lifecycle/` (plan.md, spec.md, data-model.md, contracts/, research.md, quickstart.md)
**Tests**: Unit tests included only for flag derivation and daemon logic (critical correctness). No integration tests — verified manually via quickstart.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (no dependency on other in-progress task)
- **[Story]**: User story this task belongs to (US1–US6)
- Every task includes exact file path and implementation notes

## Context Reference (read before implementing any task)

Key constants used throughout:
- **Challenges namespace**: `challenges`
- **Controller namespace**: `ctfd`
- **Annotation key**: `ctf/activated-at` (value: UTC ISO 8601 string e.g. `"2026-03-24T14:00:00+00:00"`)
- **Managed label set**: `team={team_id}`, `challenge={challenge_id}`, `managed-by=ctf-controller`
- **NGINX TCP ConfigMap**: name=`tcp-services`, namespace=`ingress-nginx`
- **TCP entry format**: `"{port}": "challenges/{svc-name}:{target-port}"`
- **TCP port pool**: starts at 30000; always read existing ConfigMap before assigning
- **Flag formula**: `infodays{hmac.new(CTF_MASTER_SECRET.encode(), f"{team_id}:{challenge_id}".encode(), "sha256").hexdigest()[:32]}`
- **Naming**: Deployment=`team-{team_id}-{challenge_id}`, Secret=`team-{team_id}-{challenge_id}-secret`, Service=`team-{team_id}-{challenge_id}-svc`, Ingress=`team-{team_id}-{challenge_id}-ingress`
- **Test resources**: team_id=`999`, challenge IDs prefixed `test-`
- **Controller API**: 2 replicas, 0.25 CPU limit, 256Mi RAM limit
- **Lifetime daemon**: 1 replica, 0.1 CPU limit, 128Mi RAM limit
- **Challenge pod limits**: 0.5 CPU, 128Mi RAM (set in Deployment spec)
- **DOCR image prefix**: `registry.digitalocean.com/infodays-registry/`

---

## Phase 1: Setup

**Purpose**: Create project skeleton, dependencies, and Docker build files.

- [x] T001 Create directory structure: `controller/`, `ctfd-plugin/assets/`, `challenges/manifests/`, `k8s/controller/`, `scripts/`, `tests/unit/`, `tests/integration/`
  - Run: `mkdir -p controller ctfd-plugin/assets challenges/manifests k8s/controller scripts tests/unit tests/integration`
  - Create empty `__init__.py` in `controller/` and `tests/unit/` and `tests/integration/`

- [x] T002 Create `controller/requirements.txt` with pinned dependencies
  - Include: `fastapi>=0.111.0`, `uvicorn[standard]>=0.29.0`, `kubernetes>=29.0.0`, `pydantic>=2.0.0`, `httpx>=0.27.0`, `python-dotenv>=1.0.0`
  - Add dev deps comment: `# pytest>=8.0.0  pytest-asyncio>=0.23.0` (not required at runtime)

- [x] T003 [P] Create `controller/Dockerfile` for the controller API image
  - Base image: `python:3.11-slim`
  - `WORKDIR /app`
  - `COPY requirements.txt .` then `RUN pip install --no-cache-dir -r requirements.txt`
  - `COPY . .`
  - `USER 1000` (non-root, per constitution)
  - `EXPOSE 5000`
  - `CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1"]`

- [x] T004 [P] Create `controller/daemon.Dockerfile` for the lifetime daemon image
  - Same base and pip install as T003
  - `CMD ["python", "daemon.py"]`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared utilities used by multiple components. MUST be complete before any user story.

**⚠️ CRITICAL**: US1, US2, US3, US4, US6 all depend on this phase.

- [x] T005 Create `controller/k8s_client.py` — Kubernetes client initialiser
  - Define `init_k8s_client() -> tuple[AppsV1Api, CoreV1Api, NetworkingV1Api]`
  - Body: try `kubernetes.config.load_incluster_config()`, except `ConfigException` → `kubernetes.config.load_kube_config()`
  - Return `(client.AppsV1Api(), client.CoreV1Api(), client.NetworkingV1Api())`
  - Import: `from kubernetes import client, config; from kubernetes.client.rest import ApiException`
  - This function is called once at startup (in FastAPI lifespan and daemon main)

- [x] T006 Create `controller/flag.py` — flag derivation + CLI
  - Import: `import hmac, hashlib, os, sys, argparse`
  - Define `derive_flag(team_id: str, challenge_id: str) -> str`
  - Body: read `CTF_MASTER_SECRET = os.environ["CTF_MASTER_SECRET"]` (raise `KeyError` if missing — do NOT default to empty string)
  - Compute: `digest = hmac.new(CTF_MASTER_SECRET.encode(), f"{team_id}:{challenge_id}".encode(), "sha256").hexdigest()[:32]`
  - Return: `f"infodays{{{digest}}}"`
  - CLI: `if __name__ == "__main__"` block with `argparse` accepting `--team` and `--challenge`, prints derived flag
  - Example: `python flag.py --team 3 --challenge web-sqli` → `infodays{a3f1c2...}`

- [x] T007 Create `controller/manifest_loader.py` — challenge manifest reader
  - Import: `import yaml, os, pathlib`
  - Define `load_manifests(manifest_dir: str = "challenges/manifests") -> list[dict]`
  - Body: glob `*.yaml` files in manifest_dir (skip `schema.yaml`), parse each with `yaml.safe_load`, return list
  - Each manifest dict has keys: `id`, `name`, `category`, `image`, `port`, `type`, `points`, `memory_limit` (optional, default `"128Mi"`)
  - Service challenge categories: `{"web", "pwn", "misc"}` — filter for these in bulk_spawn
  - File challenge categories: `{"crypto", "forensics", "reversing", "osint"}` — skipped by bulk_spawn

- [x] T008 [P] Create `controller/naming.py` — K8s resource naming helpers
  - Define these pure functions (no I/O):
    - `deployment_name(team_id: str, challenge_id: str) -> str` → `f"team-{team_id}-{challenge_id}"`
    - `secret_name(team_id: str, challenge_id: str) -> str` → `f"team-{team_id}-{challenge_id}-secret"`
    - `service_name(team_id: str, challenge_id: str) -> str` → `f"team-{team_id}-{challenge_id}-svc"`
    - `ingress_name(team_id: str, challenge_id: str) -> str` → `f"team-{team_id}-{challenge_id}-ingress"`
    - `managed_labels(team_id: str, challenge_id: str) -> dict` → `{"team": team_id, "challenge": challenge_id, "managed-by": "ctf-controller"}`

- [x] T009 [P] Create `controller/exceptions.py` — custom exception classes
  - `class ChallengeNotFound(Exception): pass`
  - `class MaxInstancesExceeded(Exception): pass`
  - `class ControllerKeyInvalid(Exception): pass`
  - These are raised by service logic and caught by FastAPI exception handlers

- [x] T010 Create `challenges/manifests/schema.yaml` — documented manifest format
  - Copy the JSON Schema content from `specs/003-challenge-controller-pod-lifecycle/contracts/challenge-manifest-schema.yaml`
  - This file is documentation only — not validated at runtime in this phase

- [x] T011 [P] Create example challenge manifests in `challenges/manifests/`
  - Create `challenges/manifests/web-sqli.yaml`: `{id: web-sqli, name: "SQL Injection", category: web, image: registry.digitalocean.com/infodays-registry/web-sqli:latest, port: 80, type: http, points: 100}`
  - Create `challenges/manifests/pwn-bof.yaml`: `{id: pwn-bof, name: "Buffer Overflow", category: pwn, image: registry.digitalocean.com/infodays-registry/pwn-bof:latest, port: 1337, type: tcp, points: 250}`
  - Create `challenges/manifests/misc-riddle.yaml`: `{id: misc-riddle, name: "TCP Riddle", category: misc, image: registry.digitalocean.com/infodays-registry/misc-riddle:latest, port: 4444, type: tcp, points: 150}`

**Checkpoint**: Foundation ready — T005–T011 complete. All user story phases can now begin.

---

## Phase 3: User Story 1 — Admin Pre-Spawns All Challenge Pods (Priority: P1) 🎯 MVP

**Goal**: `bulk_spawn.py` creates all (team × service-challenge) K8s resources in `challenges` namespace at `replicas=0`. Idempotent. Parallel execution via ThreadPoolExecutor.

**Independent Test**: Run `CTF_MASTER_SECRET=test python controller/bulk_spawn.py --ctfd-url https://ctfd.infodays.net --token $TOKEN`. Verify via `kubectl get deploy,secret,svc -n challenges -l managed-by=ctf-controller`. Re-run → all print "Skipped (exists)".

- [x] T012 [US1] Create `controller/bulk_spawn.py` skeleton with CLI entry point and CTFd teams fetcher
  - Import: `import os, sys, argparse, logging, base64, json, concurrent.futures` + `httpx` + modules from `k8s_client`, `flag`, `manifest_loader`, `naming`
  - Define `fetch_teams(ctfd_url: str, admin_token: str) -> list[dict]`
  - Body: `GET {ctfd_url}/api/v1/teams?per_page=100` with header `Authorization: Token {admin_token}`, parse `.data[]` list, return list of `{id: str, name: str}` dicts
  - CLI: `argparse` with `--ctfd-url` and `--token` args; call `main(ctfd_url, token)`
  - Logging: `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")`

- [x] T013 [US1] Implement `create_secret()` in `controller/bulk_spawn.py`
  - Signature: `create_secret(core_v1: CoreV1Api, team_id: str, challenge: dict) -> str`
    - Returns `"created"` or `"skipped"`
  - Build Secret body: `V1Secret(metadata=V1ObjectMeta(name=secret_name(team_id, challenge["id"]), namespace="challenges", labels=managed_labels(team_id, challenge["id"])), string_data={"FLAG": derive_flag(team_id, challenge["id"])})`
  - Call `core_v1.create_namespaced_secret("challenges", body)`
  - Catch `ApiException` with `status==409` → log `"Skipped (exists): {secret_name(...)}"`, return `"skipped"`
  - On success → log `"Created secret: {secret_name(...)}"`, return `"created"`

- [x] T014 [US1] Implement `create_deployment()` in `controller/bulk_spawn.py`
  - Signature: `create_deployment(apps_v1: AppsV1Api, team_id: str, challenge: dict) -> str`
  - Build Deployment body with:
    - `metadata.name = deployment_name(team_id, challenge["id"])`, `namespace="challenges"`, `labels=managed_labels(...)`, `annotations={"ctf/activated-at": ""}`
    - `spec.replicas = 0`
    - `spec.selector.match_labels = managed_labels(...)` (same labels)
    - `spec.template.metadata.labels = managed_labels(...)`
    - Container: `name=challenge["id"]`, `image=challenge["image"]`, `ports=[{containerPort: challenge["port"]}]`
    - `env=[V1EnvVar(name="FLAG", value_from=V1EnvVarSource(secret_key_ref=V1SecretKeySelector(name=secret_name(team_id, challenge["id"]), key="FLAG")))]`
    - Resources: `limits={"cpu": "0.5", "memory": challenge.get("memory_limit", "128Mi")}, requests={"cpu": "0.1", "memory": "32Mi"}`
  - Call `apps_v1.create_namespaced_deployment("challenges", body)`
  - Catch 409 → `"skipped"`, success → `"created"`

- [x] T015 [US1] Implement `create_service()` in `controller/bulk_spawn.py`
  - Signature: `create_service(core_v1: CoreV1Api, team_id: str, challenge: dict) -> str`
  - Build Service: `type=ClusterIP`, selector=`managed_labels(team_id, challenge["id"])`, port=`challenge["port"]`
  - `metadata.name=service_name(team_id, challenge["id"])`, `namespace="challenges"`, `labels=managed_labels(...)`
  - Catch 409 → `"skipped"`, success → `"created"`

- [x] T016 [US1] Implement `create_http_ingress()` in `controller/bulk_spawn.py` (for `type=http` challenges only)
  - Signature: `create_http_ingress(net_v1: NetworkingV1Api, team_id: str, challenge: dict) -> str`
  - Host: `f"team-{team_id}-{challenge['id']}.challenges.infodays.net"`
  - Build `V1Ingress` with:
    - `metadata.annotations = {"cert-manager.io/cluster-issuer": "letsencrypt-prod", "nginx.ingress.kubernetes.io/ssl-redirect": "true"}`
    - `spec.ingress_class_name = "nginx"`
    - `spec.rules = [{host: ..., http: {paths: [{path: "/", pathType: "Prefix", backend: {service: {name: service_name(...), port: {number: challenge["port"]}}}}]}}]`
    - `spec.tls = [{hosts: [host], secretName: f"team-{team_id}-{challenge['id']}-tls"}]`
  - Catch 409 → `"skipped"`, success → `"created"`

- [x] T017 [US1] Implement `add_tcp_entry()` in `controller/bulk_spawn.py` (for `type=tcp` challenges only)
  - Signature: `add_tcp_entry(core_v1: CoreV1Api, team_id: str, challenge: dict) -> tuple[str, int]`
    - Returns `("created"|"skipped", port_number)`
  - Step 1: Read existing ConfigMap: `cm = core_v1.read_namespaced_config_map("tcp-services", "ingress-nginx")`; `existing = cm.data or {}`
  - Step 2: Build expected value string: `expected_val = f"challenges/{service_name(team_id, challenge['id'])}:{challenge['port']}"`
  - Step 3: Check if any key in `existing` already maps to `expected_val` → if found, return `("skipped", int(key))`
  - Step 4: Assign new port: `assigned_port = max((int(k) for k in existing.keys() if k.isdigit()), default=29999) + 1`
  - Step 5: Patch ConfigMap: `core_v1.patch_namespaced_config_map("tcp-services", "ingress-nginx", {"data": {str(assigned_port): expected_val}})`
  - Return `("created", assigned_port)`

- [x] T018 [US1] Implement `spawn_one()` and `main()` with `ThreadPoolExecutor` in `controller/bulk_spawn.py`
  - Define `spawn_one(clients: tuple, team: dict, challenge: dict) -> dict`
    - Calls `create_secret`, `create_deployment`, `create_service`, then `create_http_ingress` (if `type==http`) or `add_tcp_entry` (if `type==tcp`)
    - Returns summary dict `{team_id, challenge_id, status: "created"|"skipped"|"error", error: str|None}`
  - Define `main(ctfd_url: str, admin_token: str)`
    - Init K8s clients: `apps_v1, core_v1, net_v1 = init_k8s_client()`
    - Fetch teams: `teams = fetch_teams(ctfd_url, admin_token)`
    - Load manifests: `challenges = [c for c in load_manifests() if c["category"] in {"web", "pwn", "misc"}]`
    - Submit all `(team, challenge)` pairs to `ThreadPoolExecutor(max_workers=10)` using `executor.submit(spawn_one, (apps_v1, core_v1, net_v1), team, challenge)`
    - Collect with `concurrent.futures.as_completed(futures)`, handle `TimeoutError` (30s per future)
    - Print summary: `f"Done: {created} created, {skipped} skipped, {errors} errors"`

**Checkpoint**: `bulk_spawn.py` fully functional. Run against k3d to verify 5 test teams × 3 manifests = 15 Deployments.

---

## Phase 4: User Story 2 — Team Activates a Challenge Instance (Priority: P1)

**Goal**: FastAPI controller with `/activate`, `/status/{team_id}`, and `/health`. Auth via `X-Controller-Key`. Runs at 2 replicas.

**Independent Test**: `curl -X POST http://localhost:5000/activate -H "X-Controller-Key: testkey" -H "Content-Type: application/json" -d '{"team_id":"999","challenge_id":"test-web-sqli"}'` → 200 `{status: "starting", url: "..."}`. Verify deployment replicas=1 and annotation set in K8s.

- [x] T019 [US2] Create `controller/api.py` skeleton: FastAPI app with lifespan context manager
  - Import: `import os, secrets, hmac as hmac_lib, hashlib, logging` + fastapi, pydantic, kubernetes modules, `naming`, `exceptions`, `k8s_client`
  - Define lifespan:
    ```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not os.getenv("CTF_MASTER_SECRET"):
            raise ValueError("CTF_MASTER_SECRET env var not set")
        if not os.getenv("CONTROLLER_KEY"):
            raise ValueError("CONTROLLER_KEY env var not set")
        apps_v1, core_v1, _ = init_k8s_client()
        app.state.apps_v1 = apps_v1
        app.state.core_v1 = core_v1
        yield
    ```
  - `app = FastAPI(lifespan=lifespan)`
  - Register exception handlers: `ChallengeNotFound` → 404, `MaxInstancesExceeded` → 429 with message `"Max 4 active instances reached. Stop one to continue."`, `ControllerKeyInvalid` → 401

- [x] T020 [US2] Implement `verify_controller_key` dependency and request/response models in `controller/api.py`
  - Pydantic models: `class ActivateRequest(BaseModel): team_id: str; challenge_id: str`
  - Same for `DeactivateRequest`
  - Response models: `class ActivateResponse(BaseModel): status: str; url: str` and `class StatusResponse(BaseModel): challenges: list[dict]`
  - Auth dependency:
    ```python
    def verify_controller_key(x_controller_key: str = Header(...)):
        expected = os.getenv("CONTROLLER_KEY", "")
        if not secrets.compare_digest(x_controller_key.encode(), expected.encode()):
            raise ControllerKeyInvalid()
    ```
  - Apply to all routes via `dependencies=[Depends(verify_controller_key)]` on the router, **except** `/health`

- [x] T021 [US2] Implement `POST /activate` endpoint in `controller/api.py`
  - Signature: `async def activate(req: ActivateRequest, request: Request, _=Depends(verify_controller_key))`
  - Step 1: Get `apps_v1 = request.app.state.apps_v1`
  - Step 2: Count active pods: `deploys = apps_v1.list_namespaced_deployment("challenges", label_selector=f"team={req.team_id},managed-by=ctf-controller").items`; `active_count = sum(1 for d in deploys if d.spec.replicas == 1)`
  - Step 3: If `active_count >= 4` → raise `MaxInstancesExceeded`
  - Step 4: Resolve deployment name: `dep_name = deployment_name(req.team_id, req.challenge_id)`; try `apps_v1.read_namespaced_deployment(dep_name, "challenges")` → if 404 → raise `ChallengeNotFound`
  - Step 5: Build patch: `{"spec": {"replicas": 1}, "metadata": {"annotations": {"ctf/activated-at": datetime.now(timezone.utc).isoformat()}}}`
  - Step 6: `apps_v1.patch_namespaced_deployment(dep_name, "challenges", patch_body)`
  - Step 7: Build URL: if challenge type is `http` → `f"https://team-{req.team_id}-{req.challenge_id}.challenges.infodays.net"`, else read TCP port from NGINX ConfigMap and return `f"nc challenges.infodays.net {port}"`
  - Return: `{"status": "starting", "url": url}`
  - Note on URL building for TCP: read `core_v1 = request.app.state.core_v1`; `cm = core_v1.read_namespaced_config_map("tcp-services", "ingress-nginx")`; find key whose value contains `service_name(req.team_id, req.challenge_id)`; port = that key

- [x] T022 [US2] Implement `GET /status/{team_id}` endpoint in `controller/api.py`
  - Signature: `async def get_status(team_id: str, request: Request, _=Depends(verify_controller_key))`
  - List deployments: `deploys = apps_v1.list_namespaced_deployment("challenges", label_selector=f"team={team_id},managed-by=ctf-controller").items`
  - If empty: return `{"challenges": []}` (200, never 404)
  - For each deployment:
    - `challenge_id = deploy.metadata.labels.get("challenge")`
    - `replicas = deploy.spec.replicas`
    - `activated_at = deploy.metadata.annotations.get("ctf/activated-at", "")`
    - Compute status: if `replicas==1` → `"running"`, elif `replicas==0 and activated_at` → `"suspended"`, elif `replicas==0 and not activated_at` → `"fresh"`, else → `"unknown"`
    - Build URL: same logic as T021 (http → subdomain, tcp → nc command from ConfigMap)
  - Return: `{"challenges": [{"challenge_id": ..., "status": ..., "url": url_or_null, "activated_at": activated_at_or_null}, ...]}`

- [x] T023 [US2] Implement `GET /health` endpoint in `controller/api.py`
  - No auth required — no `Depends(verify_controller_key)` on this route
  - Return: `{"status": "ok"}` with HTTP 200

- [x] T024 [US2] Create `k8s/controller/api-deployment.yaml` — controller FastAPI K8s manifest
  - Deployment: `name=controller-api`, `namespace=ctfd`, `replicas=2`
  - Labels: `app=controller-api`
  - Container: `name=controller-api`, `image=registry.digitalocean.com/infodays-registry/controller-api:latest`
  - Resources: `limits: {cpu: "250m", memory: "256Mi"}`
  - Env vars (from secrets):
    - `CTF_MASTER_SECRET`: from `secretKeyRef name=ctfd-secrets key=CTF_MASTER_SECRET`
    - `CONTROLLER_KEY`: from `secretKeyRef name=controller-key key=CONTROLLER_KEY`
  - LivenessProbe: `httpGet path=/health port=5000, initialDelaySeconds=10, periodSeconds=15`
  - ReadinessProbe: same path, `initialDelaySeconds=5`
  - Service: `name=controller-api`, `namespace=ctfd`, `type=ClusterIP`, port 80→5000

**Checkpoint**: Deploy api-deployment.yaml to k3d. Call `/activate` and `/status`. Verify 2 running pods, replicas=1 in target deployment, annotation set.

---

## Phase 5: User Story 3 — Team Deactivates a Challenge Instance (Priority: P2)

**Goal**: `POST /deactivate` scales Deployment to replicas=0 and clears `ctf/activated-at` annotation via read-modify-write.

**Independent Test**: Call `/activate` to start a pod, then `POST /deactivate`. Verify replicas=0, annotation cleared. Call `/activate` again — verify it succeeds (slot freed).

- [x] T025 [US3] Implement annotation-clearing helper `clear_activation_annotation()` in `controller/api.py`
  - Signature: `def clear_activation_annotation(apps_v1: AppsV1Api, dep_name: str) -> None`
  - Use read-modify-write (strategic merge patch with `None` does not reliably remove keys):
    1. `deploy = apps_v1.read_namespaced_deployment(dep_name, "challenges")`
    2. `annotations = dict(deploy.metadata.annotations or {})`
    3. `annotations.pop("ctf/activated-at", None)`
    4. `apps_v1.patch_namespaced_deployment(dep_name, "challenges", {"metadata": {"annotations": annotations}, "spec": {"replicas": 0}})`
  - Idempotent: safe to call on an already-suspended deployment

- [x] T026 [US3] Implement `POST /deactivate` endpoint in `controller/api.py`
  - Signature: `async def deactivate(req: DeactivateRequest, request: Request, _=Depends(verify_controller_key))`
  - `dep_name = deployment_name(req.team_id, req.challenge_id)`
  - Try `apps_v1.read_namespaced_deployment(dep_name, "challenges")` → if 404 → raise `ChallengeNotFound`
  - Call `clear_activation_annotation(apps_v1, dep_name)`
  - Return: `{"status": "suspended"}`
  - Idempotent: calling on already-suspended deployment returns same 200 response

**Checkpoint**: `/activate` + `/deactivate` cycle works. 4-pod cap releases correctly after `/deactivate`.

---

## Phase 6: User Story 4 — Lifetime Daemon Enforces 60-Minute Timeout (Priority: P2)

**Goal**: `daemon.py` polls all managed Deployments every 5 minutes; scales expired ones (>60 min since `ctf/activated-at`) to replicas=0.

**Independent Test**: Manually backdate `ctf/activated-at` annotation to 61 minutes ago on a running Deployment. Run `python daemon.py --once`. Verify replicas=0 and annotation cleared.

- [x] T027 [US4] Create `controller/daemon.py` with `reconcile_once()` function
  - Import: `import os, sys, logging, time, argparse` + `datetime`, `timezone` + kubernetes modules + `naming`, `k8s_client`
  - Define `reconcile_once(apps_v1: AppsV1Api) -> int`
    - Returns count of pods suspended this pass
  - Body:
    1. `deploys = apps_v1.list_namespaced_deployment("challenges", label_selector="managed-by=ctf-controller").items`
    2. `now = datetime.now(timezone.utc)`
    3. For each deploy: skip if `spec.replicas != 1`; read `activated_at_str = deploy.metadata.annotations.get("ctf/activated-at", "")`; skip if empty
    4. Parse: `activated_at = datetime.fromisoformat(activated_at_str)`; elapsed = `now - activated_at`
    5. If `elapsed.total_seconds() > 3600` (60 min):
       - Read-modify-write to clear annotation and set replicas=0 (same pattern as T025)
       - Log: `logger.info(f"Auto-suspended {deploy.metadata.name} (lifetime exceeded)")`
       - Increment suspended counter
  - Return suspended count

- [x] T028 [US4] Add `main()` loop and `--once` flag to `controller/daemon.py`
  - `argparse` with `--once` flag (run one iteration then exit; for testing)
  - `main()` body:
    1. Validate `CTF_MASTER_SECRET` and any other required env vars
    2. `apps_v1, _, _ = init_k8s_client()`
    3. If `--once`: call `reconcile_once(apps_v1)` once and exit
    4. Else: `while True: reconcile_once(apps_v1); time.sleep(300)` (5 minutes)
  - Logging: `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")`

- [x] T029 [US4] Create `k8s/controller/daemon-deployment.yaml`
  - Deployment: `name=controller-daemon`, `namespace=ctfd`, `replicas=1`
  - Container: `name=controller-daemon`, `image=registry.digitalocean.com/infodays-registry/controller-daemon:latest`
  - Resources: `limits: {cpu: "100m", memory: "128Mi"}`
  - Env vars: `CTF_MASTER_SECRET` from `ctfd-secrets` secret (same as T024)
  - No ports, no liveness probe (daemon has no HTTP endpoint)
  - `restartPolicy: Always` (default)

**Checkpoint**: Deploy daemon. Backdate annotation, wait one reconcile pass (or use `--once`). Verify auto-suspend.

---

## Phase 7: User Story 5 — CTFd Plugin Shows Real-Time Instance Status (Priority: P3)

**Goal**: Minimal CTFd plugin (`ctfd-plugin/`) that adds status badge and Start/Stop buttons to web/pwn/misc challenge pages. Status auto-refreshes every 15 seconds. Error state shows "Unknown" badge.

**Independent Test**: Copy `ctfd-plugin/` into CTFd's `CTFd/plugins/` directory and restart CTFd. Visit a web challenge page as a logged-in team. Status badge, Start button (when Fresh), Stop button + URL (when Running), and Unknown badge (when controller unreachable) all render correctly.

**Note on deployment path**: The plugin source lives at `ctfd-plugin/` in this repo. At deploy time it must be copied into the running CTFd container at `/opt/CTFd/CTFd/plugins/controller-plugin/`. The CTFd deployment YAML (Phase 2) or a post-deploy step handles this copy.

- [x] T030 [US5] Create `ctfd-plugin/__init__.py` — plugin entry point
  - Signature: `def load(app)` (Flask app instance passed by CTFd)
  - Register a Flask Blueprint:
    ```python
    from flask import Blueprint
    blueprint = Blueprint("controller_plugin", __name__, static_folder="assets", static_url_path="/plugins/controller-plugin/assets")
    app.register_blueprint(blueprint)
    ```
  - Register a Jinja2 global so templates can access the config:
    ```python
    @app.context_processor
    def inject_controller_config():
        from CTFd.models import Configs
        url = Configs.query.filter_by(key="CONTROLLER_URL").first()
        return {"controller_url": url.value if url else ""}
    ```
  - Set default config values on first load (inside `with app.app_context():`):
    ```python
    from CTFd.models import Configs, db
    if not Configs.query.filter_by(key="CONTROLLER_URL").first():
        db.session.add(Configs(key="CONTROLLER_URL", value="http://controller-api.ctfd.svc.cluster.local"))
        db.session.commit()
    if not Configs.query.filter_by(key="X_CONTROLLER_KEY").first():
        db.session.add(Configs(key="X_CONTROLLER_KEY", value="CHANGE_ME"))
        db.session.commit()
    ```

- [x] T031 [US5] Add template injection hook in `ctfd-plugin/__init__.py`
  - Override or extend CTFd's challenge page template to inject a `<script>` tag
  - Use CTFd's `register_plugin_assets_directory` utility (if available in the CTFd version) or add a Jinja2 global that renders the script tag
  - The injected script writes two JS globals:
    ```html
    <script>
      window.TEAM_ID = {{ current_user.team_id or "null" }};
      window.CHALLENGE_ID = "{{ challenge.id }}";
      window.CHALLENGE_CATEGORY = "{{ challenge.category }}";
      window.CONTROLLER_URL = "{{ controller_url }}";
    </script>
    <script src="/plugins/controller-plugin/assets/plugin.js"></script>
    ```
  - Register using: `app.jinja_env.globals["inject_controller_ui"] = render_controller_ui_snippet` where the function renders the above HTML

- [x] T032 [US5] Create `ctfd-plugin/assets/plugin.js` — skeleton and status fetch
  - Structure: IIFE `(function() { ... })()`
  - First line: check `window.CHALLENGE_CATEGORY` — if not in `["web", "pwn", "misc"]`, return immediately (no-op)
  - Check `window.TEAM_ID` — if null, return immediately (no session)
  - Define `fetchStatus()` async function:
    ```js
    async function fetchStatus() {
      const key = await getControllerKey(); // reads from X_CONTROLLER_KEY config (see T033)
      const resp = await fetch(`${window.CONTROLLER_URL}/status/${window.TEAM_ID}`, {
        headers: {"X-Controller-Key": key}
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      return data.challenges.find(c => c.challenge_id === window.CHALLENGE_ID) || null;
    }
    ```
  - On fetch error: call `renderUnknown()` (see T034) and log `console.error("Controller unreachable:", err)`
  - Call `fetchStatus()` on page load and every 15 seconds: `setInterval(updateUI, 15000)`

- [x] T033 [US5] Add badge and URL rendering functions to `ctfd-plugin/assets/plugin.js`
  - Define `renderUI(challenge)` — injected into a container `<div id="ctf-controller-ui">` that the plugin creates and appends to the challenge description area
  - Logic:
    - `status === "fresh"` → grey badge "Fresh" + enabled "▶ Start Instance" button; no URL shown
    - `status === "suspended"` → grey badge "Suspended" + enabled "▶ Start Instance" button; no URL shown
    - `status === "running"` → green badge "Running" + enabled "⏹ Stop Instance" button + URL link + note `"(starting, may take ~30 seconds if just activated)"`
    - `status === "unknown"` or null → grey badge "Unknown" + disabled button + `<a href="#">Retry</a>` link that calls `fetchStatus()` manually
  - Define `renderUnknown()` that sets the same "Unknown" state as above

- [x] T034 [US5] Add Start/Stop click handlers to `ctfd-plugin/assets/plugin.js`
  - Start handler (called when "▶ Start Instance" clicked):
    ```js
    async function handleStart() {
      setButtonLoading(true);
      const resp = await fetch(`${window.CONTROLLER_URL}/activate`, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Controller-Key": key},
        body: JSON.stringify({team_id: String(window.TEAM_ID), challenge_id: window.CHALLENGE_ID})
      });
      const data = await resp.json();
      if (resp.status === 429) { alert(data.error); return; }
      if (!resp.ok) { renderUnknown(); return; }
      renderUI({challenge_id: window.CHALLENGE_ID, status: "running", url: data.url, activated_at: new Date().toISOString()});
    }
    ```
  - Stop handler: similar, calls `/deactivate`, on 200 re-renders as "suspended"
  - `setButtonLoading(loading)`: disables button and sets text to "Starting…" / "Stopping…" while request is in-flight
  - `getControllerKey()`: reads `X_CONTROLLER_KEY` value from a hidden element the Python template rendered (or from `window.CONTROLLER_KEY` set by the template)

**Checkpoint**: Plugin visible on challenge page. Start → Running + URL shown. Stop → Suspended. Controller down → "Unknown" + Retry.

---

## Phase 8: User Story 6 — Admin Imports Derived Flags into CTFd (Priority: P3)

**Goal**: `import_flags.py` pushes one derived flag per (team × service-challenge) pair to CTFd admin API. Idempotent.

**Independent Test**: Run `CTFD_ADMIN_TOKEN=$TOKEN CTF_MASTER_SECRET=x python controller/import_flags.py --ctfd-url https://ctfd.infodays.net`. Check CTFd admin → Challenges → each service challenge → Flags. Verify each team has exactly one flag matching `infodays{...}`.

- [x] T035 [US6] Create `controller/import_flags.py`
  - Import: `import os, sys, argparse, logging, httpx`; from `flag` import `derive_flag`; from `manifest_loader` import `load_manifests`
  - Define `fetch_teams(ctfd_url, token) -> list[dict]`: same as in `bulk_spawn.py` (copy or import)
  - Define `fetch_existing_flags(ctfd_url, token, challenge_id: str) -> set[str]`:
    - `GET {ctfd_url}/api/v1/flags?per_page=500` with admin token
    - Return set of flag strings already registered for that challenge
  - Define `import_flag(ctfd_url, token, team_id, challenge: dict) -> str`:
    - Compute flag: `flag_str = derive_flag(str(team_id), challenge["id"])`
    - Check if flag already exists for this challenge: `GET {ctfd_url}/api/v1/flags` filtered by challenge ID
    - If flag string already in existing set → log `"Skipped (exists)"`, return `"skipped"`
    - Else: `POST {ctfd_url}/api/v1/flags` body: `{"challenge_id": challenge_ctfd_id, "type": "static", "content": flag_str, "data": ""}`
    - Return `"created"`
  - `main()`: fetch teams, load service-challenge manifests, for each `(team, challenge)` call `import_flag`, print summary
  - CLI: `--ctfd-url` arg; reads `CTFD_ADMIN_TOKEN` and `CTF_MASTER_SECRET` from environment
  - **Note**: CTFd challenge IDs in the API may differ from manifest `id` strings. The script must first `GET /api/v1/challenges` to build a map of `{challenge_name → ctfd_id}`, then match by manifest `name` field

**Checkpoint**: Run against test CTFd with 5 test teams × 3 service challenges. Verify 15 flags in CTFd admin panel.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Teardown tooling, K8s manifest validation, and quickstart verification.

- [x] T036 [P] Create `scripts/teardown-challenges.sh`
  - Bash script, `set -euo pipefail`
  - Print warning: `"WARNING: This will delete ALL resources labeled managed-by=ctf-controller in the challenges namespace."`
  - Prompt: `read -p "Type 'yes' to confirm: " CONFIRM; [ "$CONFIRM" != "yes" ] && echo "Aborted." && exit 1`
  - Execute deletions in order:
    ```bash
    kubectl delete ingress -n challenges -l managed-by=ctf-controller
    kubectl delete svc     -n challenges -l managed-by=ctf-controller
    kubectl delete deploy  -n challenges -l managed-by=ctf-controller
    kubectl delete secret  -n challenges -l managed-by=ctf-controller
    ```
  - Print: `"Teardown complete. Verifying..."`
  - Run `kubectl get all -n challenges -l managed-by=ctf-controller` to confirm empty
  - Do NOT touch `ingress-nginx/tcp-services` ConfigMap — TCP port cleanup is a separate manual step

- [x] T037 [P] Validate K8s manifests with dry-run
  - Run: `kubectl apply --dry-run=client -f k8s/controller/api-deployment.yaml`
  - Run: `kubectl apply --dry-run=client -f k8s/controller/daemon-deployment.yaml`
  - Fix any validation errors before marking complete

- [x] T038 Create `controller/unit_tests/test_flag.py` — unit tests for flag derivation
  - Test 1: `derive_flag("3", "web-sqli")` with `CTF_MASTER_SECRET=test-secret` returns string matching `r"^infodays\{[0-9a-f]{32}\}$"`
  - Test 2: Different team IDs produce different flags
  - Test 3: Different challenge IDs produce different flags
  - Test 4: Missing `CTF_MASTER_SECRET` env var raises `KeyError`
  - Use `pytest` with `monkeypatch.setenv("CTF_MASTER_SECRET", "test-secret")`

- [x] T039 Run quickstart.md validation scenarios against k3d
  - Follow the steps in `specs/003-challenge-controller-pod-lifecycle/quickstart.md` exactly
  - Verify each test flow (flag derivation, activate, 4-pod cap, daemon expiry) passes
  - Document any deviations from expected output in a note on this task

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)       → No dependencies. Start immediately.
Phase 2 (Foundation)  → Depends on Phase 1. BLOCKS all user stories.
Phase 3 (US1)         → Depends on Phase 2.
Phase 4 (US2)         → Depends on Phase 2. Can run in parallel with Phase 3.
Phase 5 (US3)         → Depends on Phase 4 (adds to api.py). Sequential with Phase 4.
Phase 6 (US4)         → Depends on Phase 2. Can run in parallel with Phases 3–5.
Phase 7 (US5)         → Depends on Phase 4 (needs /activate, /status endpoints to exist).
Phase 8 (US6)         → Depends on Phase 2. Can run in parallel with Phases 3–5.
Phase 9 (Polish)      → Depends on all phases complete.
```

### User Story Dependencies

```
US1 (bulk_spawn)  ──► independent after Phase 2
US2 (/activate)   ──► independent after Phase 2
US3 (/deactivate) ──► depends on US2 (same api.py file, needs app skeleton from T019)
US4 (daemon)      ──► independent after Phase 2
US5 (plugin)      ──► depends on US2 (needs /activate, /status endpoints running)
US6 (import_flags)──► independent after Phase 2
```

### Within Each Phase

- T008, T009, T010, T011 are [P] — different files, run in parallel after T005–T007
- T013, T014, T015 are [P] within US1 — each creates a different K8s resource type
- T016, T017 are [P] — only one fires per challenge type
- T019 MUST complete before T020–T024 (US2 skeleton first)
- T025 MUST complete before T026 (helper before endpoint)
- T030 MUST complete before T031–T034 (Blueprint registration first)
- T032 MUST complete before T033, T034 (fetch logic before render/click)

---

## Parallel Execution Examples

### Phase 2 — Foundational (after T005 done)

```
Parallel batch:
  T008 → controller/naming.py
  T009 → controller/exceptions.py
  T010 → challenges/manifests/schema.yaml
  T011 → challenges/manifests/*.yaml examples
```

### Phase 3 — US1 Spawn Resources (after T012)

```
Parallel batch:
  T013 → create_secret()
  T014 → create_deployment()
  T015 → create_service()
Then sequential:
  T016 → create_http_ingress()  |  T017 → add_tcp_entry()  (parallel, different challenge types)
Then:
  T018 → wire up ThreadPoolExecutor in main()
  T019 → idempotency (409 handling) added to all create_ functions above
```

### Phase 4 + Phase 6 (after Phase 2)

```
In parallel:
  Stream A: T019 → T020 → T021 → T022 → T023 → T024  (US2 controller API)
  Stream B: T027 → T028 → T029                         (US4 daemon)
```

---

## Implementation Strategy

### MVP: US1 + US2 Only

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundation)
3. Complete Phase 3 (US1 — bulk_spawn)
4. Complete Phase 4 (US2 — /activate, /status, /health, K8s manifest)
5. **STOP**: Pre-spawn test resources + call `/activate` manually → verify end-to-end
6. Deploy to k3d and validate

### Incremental Delivery

1. Setup + Foundation → shared utils ready
2. US1 → resources spawn correctly
3. US2 → teams can activate; US3 → teams can deactivate (extend api.py)
4. US4 → lifetime enforced automatically
5. US5 → CTFd plugin wires it all together
6. US6 → flags registered in CTFd before event

---

## Notes

- `[P]` = different file or independent scope; no in-progress task dependency
- `[USn]` = maps to user story from spec.md for traceability
- Every task has an exact file path — no guessing required
- Cheaper model guidance: read the **Context Reference** section at the top before starting any task; it contains all naming conventions, K8s API patterns, and key constants
- Idempotency is non-negotiable: all create operations must handle 409 Conflict gracefully
- Annotation clearing MUST use read-modify-write (not strategic merge patch with `None`) — see T025
- The controller API is stateless: all state is in K8s Deployment annotations and the NGINX ConfigMap
- Test resource convention: `team_id="999"`, challenge IDs prefixed with `test-`
