# Implementation Plan: Challenge Controller & Pod Lifecycle

**Branch**: `003-challenge-controller-pod-lifecycle` | **Date**: 2026-03-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/003-challenge-controller-pod-lifecycle/spec.md`

## Summary

Build the Python challenge controller for InfoDays CTF: a bulk pre-spawn script
that creates all (team × service-challenge) Kubernetes resources at `replicas=0`
before the event, a minimal FastAPI that the CTFd plugin calls to activate/deactivate
pods and check status, a lifetime daemon that enforces a 60-minute per-instance
timeout, a flag import script, a minimal CTFd plugin for in-page Start/Stop UI,
and a teardown script. The controller runs in the `ctfd` namespace; all challenge
pods live in the `challenges` namespace.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `kubernetes` (official Python client), `fastapi`, `uvicorn`, `httpx` (for CTFd API calls), `pydantic`
**Storage**: No persistent storage — all lifecycle state is held in Kubernetes Deployment annotations (`ctf/activated-at`) and the NGINX TCP ConfigMap
**Testing**: pytest (unit + integration), k3d for local cluster, bash scripts for infrastructure smoke tests
**Target Platform**: Linux container (DOKS pod in `ctfd` namespace); local dev via k3d
**Project Type**: Python service (controller API) + Python daemon + Python CLI scripts + CTFd plugin
**Performance Goals**: `/activate` and `/deactivate` < 2 s p95; daemon loop completes within 30 s for 50 teams × 5 challenges
**Constraints**: CPU limit 0.25 / RAM 256 Mi (controller API per constitution § V); CPU 0.1 / RAM 128 Mi (daemon); single uvicorn worker (stateless, no shared-memory requirement)
**Scale/Scope**: 50 teams × up to 15 service challenges = 750 Deployments maximum; 4 concurrent activations per team

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Flag Integrity** | Flags MUST use `HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32]`; secret from K8s Secret `ctfd-secrets` only; never logged or baked into images | PASS — `flag.py` derives flags at spawn time; stored in K8s Secret per team/challenge; `FLAG` env var injected at runtime |
| **I. Flag Integrity** | `CTF_MASTER_SECRET` MUST NOT appear in any committed file | PASS — read from env var sourced from K8s Secret; controller fails to start if unset |
| **II. Security-First Pod Isolation** | All challenge pods MUST run as uid=1000, no root, no package managers in final layers | PASS — enforced by PodSecurityStandard `restricted` on `challenges` namespace; bulk_spawn.py sets explicit securityContext (runAsNonRoot, runAsUser=1000, drop ALL caps, seccomp RuntimeDefault) to pass admission |
| **III. Pod Lifecycle Discipline** | Pre-spawn at `replicas=0`; max 4 simultaneous active pods per team; 60-min lifetime; daemon every 5 min; NEVER delete Deployments | PASS — all constraints directly implemented |
| **IV. DigitalOcean-Exclusive** | Python k8s client, FastAPI, DOCR — no external cloud services | PASS — no external cloud dependencies; controller image pushed to DOCR |
| **V. Resource & Cost Discipline** | Controller API: 0.25 CPU / 256 Mi RAM; Daemon: 0.1 CPU / 128 Mi RAM | PASS — resource limits in K8s manifests match constitution table |
| **Language & Tooling** | Python 3.11+, FastAPI (not Flask/Django), pytest | PASS |
| **Naming Conventions** | `team-{id}-{challenge-id}`, `team-{id}-{challenge-id}-secret`, `team-{id}-{challenge-id}-svc` | PASS |
| **CTFd Plugin Constraints** | Plugin MUST NOT alter flag validation, scoring, or other categories | PASS — plugin adds UI affordances only |
| **v1 Scope Boundaries** | No on-demand pod creation, no per-player instances, no monitoring | PASS — pre-spawn model; per-team only |

**Gate result: PASS — no violations. Proceed to Phase 0.**

---

## Project Structure

### Documentation (this feature)

```text
specs/003-challenge-controller-pod-lifecycle/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
controller/
├── flag.py              # derive_flag(team_id, challenge_id) → "infodays{...}"
├── bulk_spawn.py        # Pre-spawn all (team × service-challenge) K8s resources
├── api.py               # FastAPI controller — /activate, /deactivate, /status, /health
├── daemon.py            # Lifetime daemon — polls every 5 min, scales expired pods to 0
├── import_flags.py      # Pushes derived flags to CTFd admin API
├── requirements.txt
├── Dockerfile           # Controller API image
└── daemon.Dockerfile    # Daemon image

ctfd-plugin/
├── __init__.py          # CTFd plugin: register_script(), /controller-proxy/* proxy routes
└── assets/
    └── plugin.js        # Bootstrap 5 modal events, Start/Stop buttons, status polling (15s)

challenges/
└── manifests/
    ├── schema.yaml      # Documented challenge manifest format
    └── *.yaml           # One YAML manifest per challenge

k8s/
├── controller/
│   ├── api-deployment.yaml    # Controller FastAPI Deployment + Service (mounts challenge-manifests ConfigMap)
│   ├── daemon-deployment.yaml # Daemon Deployment
│   └── rbac.yaml              # ServiceAccount, Roles, and RoleBindings for ctf-controller
└── ctfd/
    └── networkpolicy.yaml     # Includes ctfd↔controller-api egress/ingress policies

scripts/
├── deploy-challenge.sh        # One-command: CTFd entry → ConfigMap → restart → bulk_spawn → flags
└── teardown-challenges.sh     # Deletes all managed-by=ctf-controller resources (with confirmation)

tests/
├── unit/
│   ├── test_flag.py
│   ├── test_activate.py
│   └── test_daemon.py
└── integration/
    ├── test_bulk_spawn.py
    └── test_api_e2e.py
```

**Structure Decision**: Single-language project structure — no frontend/backend split.
Python controller components are co-located under `controller/`; the CTFd plugin
lives separately under `ctfd-plugin/` (deployed into the CTFd container); K8s
manifests under `k8s/controller/`. This matches the layout used in Phase 2
(`k8s/ctfd/`) for consistency.

---

## Complexity Tracking

> No constitution violations — table not required.

---
