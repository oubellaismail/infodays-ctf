<!--
SYNC IMPACT REPORT
==================
Version change:   (blank template) → 1.0.0
Modified principles:
  - [PRINCIPLE_1_NAME] → I. Flag Integrity
  - [PRINCIPLE_2_NAME] → II. Security-First Pod Isolation
  - [PRINCIPLE_3_NAME] → III. Pod Lifecycle Discipline
  - [PRINCIPLE_4_NAME] → IV. DigitalOcean-Exclusive Infrastructure
  - [PRINCIPLE_5_NAME] → V. Resource & Cost Discipline
Added sections:
  - Project Identity
  - Cloud & Infrastructure
  - Kubernetes Namespaces
  - Language & Tooling
  - Challenge Categories
  - CTFd Configuration & Plugin Constraints
  - Naming Conventions
  - v1 Scope Boundaries
Removed sections: none
Templates requiring updates:
  ✅ .specify/memory/constitution.md — written now
  ⚠  .specify/templates/plan-template.md — Constitution Check gates are generic;
     update when first plan is generated to reference InfoDays principles.
  ⚠  .specify/templates/spec-template.md — no InfoDays-specific constraints yet;
     acceptable for v1 (generic spec structure still applies).
  ⚠  .specify/templates/tasks-template.md — path conventions and task categories
     are generic; acceptable for v1.
Deferred TODOs:
  - TODO(RATIFICATION_DATE): Using today (2026-03-21) as no prior date was supplied.
  - No commands/ directory exists yet; propagation check skipped.
-->

# InfoDays CTF Constitution

## Project Identity

- **Event name**: InfoDays CTF
- **Flag format**: `infodays{...}` — this exact prefix, no exceptions, no variants
- **Domain**: infodays.net
- **CTFd URL**: https://ctfd.infodays.net
- **Challenge instances**: `*.challenges.infodays.net`

## Core Principles

### I. Flag Integrity

Flags are the currency of the competition. Their derivation, storage, and
transmission MUST be tamper-proof and leak-proof at all times.

- Service challenges (web, pwn, misc) MUST use derived flags only.
  Formula: `infodays{ HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32] }`
- `CTF_MASTER_SECRET` MUST come exclusively from K8s Secret `ctfd-secrets`.
  It MUST NOT appear in any source file, `.env` file, or environment variable
  set outside of Kubernetes.
- File-based challenges (crypto, forensics, reversing, osint) MUST use static
  flags set manually in CTFd — no derivation required.
- `FLAG` MUST be injected into pods via K8s Secret as env var `FLAG`.
- `FLAG` MUST NEVER be baked into any Docker image layer.
- `FLAG` MUST NEVER be logged, printed to stdout, or exposed in any HTTP
  response header.
- K8s Secret manifests containing real values MUST be gitignored.
- `CTF_MASTER_SECRET` MUST NEVER appear in any file committed to git.

### II. Security-First Pod Isolation

Challenge pods run attacker-controlled code. The blast radius of any
exploitation MUST be contained to the individual pod.

- All challenge pods MUST run as non-root user `uid=1000`.
- No Docker image used in challenges MUST run as root.
- No package managers (apt, pip, npm, etc.) MUST appear in final image layers
  — multi-stage builds only.
- PodSecurityStandards MUST be `restricted` on the `challenges` namespace and
  `baseline` on the `ctfd` namespace.
- NetworkPolicy MUST default-deny on all namespaces; only explicitly
  allowlisted traffic is permitted.
- Challenge pods MUST NOT be able to reach: the `ctfd` namespace, other
  challenge pods, the Kubernetes API server, or the DigitalOcean metadata
  service (169.254.169.254).

### III. Pod Lifecycle Discipline

Pre-spawning and time-boxing ensure fair, predictable resource usage across
all teams during the event.

- All service-challenge Deployments MUST be pre-spawned at `replicas=0`
  before the event starts.
- A maximum of 4 pods per team MAY be at `replicas=1` (Running) simultaneously.
- Pod lifetime is exactly 60 minutes from the value of the
  `ctf/activated-at` annotation on the Deployment.
- On timeout the controller MUST scale to `replicas=0`. It MUST NEVER delete
  the Deployment.
- Deletion of Deployments is only permitted during end-of-event teardown via
  the teardown script.
- Re-activation after timeout: set `replicas=1`, reset the `ctf/activated-at`
  annotation.
- The daemon reconciliation loop MUST run every 5 minutes.

### IV. DigitalOcean-Exclusive Infrastructure

All infrastructure lives on DigitalOcean. Suggesting or introducing any other
cloud provider or external managed service is a constitution violation.

- Cloud provider: DigitalOcean only — EKS, GKE, AKS, and any other provider
  are prohibited.
- Kubernetes: DOKS (DigitalOcean Managed Kubernetes) — no self-managed K8s.
- Container registry: DOCR (DigitalOcean Container Registry) — not Docker Hub,
  not any self-hosted registry.
- Node pool: 4 × `s-4vcpu-8gb`, region `fra1`.
- Ingress: NGINX Ingress Controller — not Traefik, not Caddy.
- TLS: cert-manager + Let's Encrypt — not manual certificates, not Cloudflare
  proxy.
- Provisioning: Terraform only — no `doctl` scripts, no manual console clicks.
- Secret management: K8s Secrets only — Vault, AWS Secrets Manager, and any
  external secret store are prohibited.

### V. Resource & Cost Discipline

The cluster is sized for a single event. Over-provisioning wastes money;
under-provisioning risks service degradation. These limits are ceilings, not
starting points.

| Component        | CPU limit | RAM limit | CPU request | RAM request |
|------------------|-----------|-----------|-------------|-------------|
| Challenge pod    | 0.5       | 128Mi     | 0.1         | 32Mi        |
| CTFd (per replica) | 0.5     | 512Mi     | —           | —           |
| MySQL            | 0.5       | 1Gi       | —           | —           |
| Redis            | 0.1       | 256Mi     | —           | —           |
| Controller API   | 0.25      | 256Mi     | —           | —           |
| Lifetime daemon  | 0.1       | 128Mi     | —           | —           |

- CTFd runs at 2 replicas.
- Node size MUST NOT exceed `s-4vcpu-8gb`.
- Node count MUST NOT exceed 5.
- DOCR Starter tier is sufficient — paid tiers MUST NOT be suggested.

## Cloud & Infrastructure

- **Region**: fra1 (Frankfurt)
- **DOKS node pool**: 4 × `s-4vcpu-8gb`
- **DOCR tier**: Starter
- **Ingress**: NGINX Ingress Controller
- **TLS**: cert-manager + Let's Encrypt (HTTP-01 challenge)
- **IaC**: Terraform — all cluster, registry, DNS, and namespace resources
  MUST be declared in Terraform

## Kubernetes Namespaces

These namespaces are fixed. Renaming or repurposing them is a constitution
violation.

| Namespace    | Purpose                                                      |
|-------------|--------------------------------------------------------------|
| `ctfd`       | CTFd app, MySQL, Redis, controller API, lifetime daemon      |
| `challenges` | All challenge pods — nothing else permitted here             |
| `monitoring` | Reserved for v2 — MUST remain empty in v1                   |

## Language & Tooling

- **Controller**: Python 3.11+ using the official `kubernetes` Python client
- **Controller API**: FastAPI — Flask and Django are prohibited
- **Flag derivation**: HMAC-SHA256 exclusively (see Principle I)
- **Tests**: pytest (Python), bash (infrastructure), k6 (load)
- **Local development**: k3d — minikube, kind, and Vagrant are prohibited

## Challenge Categories

| Type          | Categories              | Pod?               | Flag type  |
|---------------|-------------------------|--------------------|------------|
| Service-based | web, pwn, misc          | Per-team pod       | Derived    |
| File-based    | crypto, forensics, reversing, osint | No pod | Static    |

- Maximum 5 challenges per category.
- Test resources MUST use `team_id=999` and challenge IDs prefixed with `test-`.

## CTFd Configuration

- **Team mode**: enabled
- **Public registration**: disabled — admin pre-creates all team accounts
- **Team size**: max 4 players per team
- **Account model**: one CTFd account per team (not per-player)

## CTFd Plugin Constraints

The plugin adds UI affordances only; it MUST NOT alter scoring or validation
logic.

- Plugin adds: status badge, Start button, Stop button, instance URL on
  challenge pages.
- Plugin calls: `/activate`, `/deactivate`, `/status` endpoints on the
  controller only.
- Plugin MUST NOT modify: flag validation, scoring, or other challenge
  categories.
- Plugin authentication: `X-Controller-Key` header sourced from a K8s Secret
  — MUST NOT be hardcoded.

## Naming Conventions

| Resource              | Pattern                                            | Example                               |
|-----------------------|----------------------------------------------------|---------------------------------------|
| K8s Deployment/Pod    | `team-{team_id}-{challenge_id}`                    | `team-3-web-sqli`                     |
| K8s Secret (flag)     | `team-{team_id}-{challenge_id}-secret`             | `team-3-web-sqli-secret`              |
| K8s labels            | `team={id}`, `challenge={id}`, `managed-by=ctf-controller` | —                           |
| Docker image          | `registry.digitalocean.com/infodays-registry/{challenge-id}:{tag}` | —          |
| Test resources        | `team_id=999`, challenge IDs prefixed with `test-` | `test-web-sqli`                       |

## v1 Scope Boundaries

The following are explicitly out of scope for v1 and MUST NOT be implemented
or suggested as part of v1 work:

- Alerting and monitoring (Prometheus, Grafana, Alertmanager) — deferred to v2
- Per-player instances — per-team instances only
- On-demand pod creation during the event — pre-spawn model only
- Any cloud vendor other than DigitalOcean
- Public or self-registration by teams

## Governance

This constitution supersedes all other practices, guidelines, and per-feature
decisions. Any deviation requires an explicit amendment following the procedure
below.

**Amendment procedure**:
1. Open a PR that edits `.specify/memory/constitution.md`.
2. Bump the version according to the semantic versioning policy below.
3. Provide a rationale comment explaining what changed and why.
4. Update any templates or docs that reference the changed rules.
5. Obtain team approval before merging.

**Versioning policy** (semantic):
- MAJOR: Backward-incompatible governance change, principle removal, or
  redefinition that invalidates prior work.
- MINOR: New principle, new section, or materially expanded guidance.
- PATCH: Clarifications, wording fixes, typo corrections.

**Compliance review**: Every implementation plan MUST include a Constitution
Check gate before Phase 0 research and re-check after Phase 1 design. Any
violation MUST be justified in the Complexity Tracking table of the plan.

---

**Version**: 1.0.0 | **Ratified**: 2026-03-21 | **Last Amended**: 2026-03-21
