# Implementation Plan: Challenge Base Images & DOCR

**Branch**: `004-base-images-docr` | **Date**: 2026-03-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-base-images-docr/spec.md`

## Summary

Build four hardened OCI base images (web, pwn, misc, static) and two helper shell scripts (`push-challenge.sh`, `setup-docr.sh`) that let challenge authors package and publish CTF challenges to the DigitalOcean Container Registry. All service images read the flag from a runtime environment variable, enforce multi-stage builds (no build tools in final layers), run as uid 1000, and validate FLAG at startup. The push script wraps the build→tag→push workflow; the setup script authenticates to DOCR and verifies DOKS↔DOCR integration.

## Technical Context

**Language/Version**: Bash 5 (scripts), Dockerfile (BuildKit ≥ 1.4), Python 3.11 (web + misc examples), C11 (pwn binary)
**Primary Dependencies**: Alpine Linux 3.19 (web, misc runtime), Ubuntu 22.04 (pwn runtime), socat 1.7 (pwn + misc), Flask 3.x (web example), Python 3.11-alpine (misc)
**Storage**: N/A for service images; `challenge.zip` artifact written to host `./dist/` via BuildKit `--output` for static builder
**Testing**: Bash smoke tests (`docker run`, `curl`, `nc`, `docker inspect`); no Python test framework needed for this phase
**Target Platform**: Linux/amd64 containers on DOKS (fra1), OCI-compatible, pullable from `challenges` namespace
**Project Type**: Container images + shell scripts
**Performance Goals**: All service images must start within 5 seconds; must fit within 0.5 CPU / 128 Mi RAM pod limits (Constitution V)
**Constraints**: Non-root uid=1000; multi-stage builds required for all three service images; FLAG never baked in; FLAG validated (non-empty) at container startup; read-only root FS on web + misc (pwn exempt); socat fork mode for concurrent connections; DOCR Starter tier
**Scale/Scope**: 4 Dockerfile directories, 2 shell scripts; images sized for ≤ 128 Mi RAM under CTF load

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I — Flag Integrity | ✅ PASS | FLAG injected via K8s Secret env var; never baked into image layers (FR-008). Service images do not derive flags — derivation happens upstream at Deployment creation time. Images simply read and serve FLAG. FLAG validated non-empty at startup (FR-008 + clarification). |
| I — FLAG never logged | ✅ PASS | Spec requires FLAG is returned only via the exploit path; entrypoint validation prints an error about the variable name, not its value. Must be enforced in implementation. |
| II — Non-root uid=1000 | ✅ PASS | FR-005 requires uid=1000 on all service images. |
| II — Multi-stage builds | ✅ PASS | FR-006 (clarified): all three service images use multi-stage builds; no build tools in final layers. |
| II — PodSecurityStandards compatible | ✅ PASS | `restricted` PSS requires non-root, no privilege escalation, no host namespaces. Images must be designed accordingly (no capabilities, no setuid binaries in runtime layer). |
| III — Pod lifecycle | ✅ N/A | Base images are templates; pod lifecycle managed by controller (Phase 3). |
| IV — DOCR only | ✅ PASS | All images tagged and pushed to `registry.digitalocean.com/infodays-registry/`. Docker Hub and other registries not referenced. |
| IV — doctl registry login | ✅ NOTE | `setup-docr.sh` uses `doctl registry login` for authentication — this is an operational step, not infrastructure provisioning. Not a constitution violation. |
| V — Resource limits | ✅ PASS | Challenge pod limit: 0.5 CPU / 128 Mi RAM. Base images must be lean (Alpine-based where possible; Ubuntu for pwn only). |

**Constitution Check result: PASS — no violations. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/004-base-images-docr/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── image-runtime-interface.md
│   ├── push-challenge-cli.md
│   └── static-builder-interface.md
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
challenges/
└── base-images/
    ├── web/
    │   ├── Dockerfile          # Multi-stage: builder (pip install) → runtime (Alpine+Python)
    │   └── app.py              # Flask SQLi example with /flag route
    ├── pwn/
    │   ├── Dockerfile          # Multi-stage: builder (gcc compile) → runtime (Ubuntu+socat)
    │   └── vuln.c              # Stack buffer overflow example, reads FLAG from env
    ├── misc/
    │   ├── Dockerfile          # Multi-stage: builder (pip install) → runtime (Alpine+Python)
    │   └── puzzle.py           # Multi-step TCP riddle, returns FLAG on all-correct
    └── static/
        └── Dockerfile          # Build-only: produces challenge.zip via BuildKit --output

scripts/
├── push-challenge.sh           # Build → tag → push wrapper for challenge authors
└── setup-docr.sh               # doctl registry login + DOKS↔DOCR integration check
```

**Structure Decision**: Single flat layout under `challenges/base-images/` by category. Scripts live in the existing `scripts/` directory alongside `setup-ctfd.sh` and `import-teams.py` from Phase 2. No new top-level directories introduced.

## Complexity Tracking

> No constitution violations — table not required.

## Phase 0: Research

See [research.md](research.md) for full findings.

**Research tasks resolved**:

1. Multi-stage Ubuntu pattern for pwn image (builder: `gcc`, runtime: `ubuntu:22.04` + `socat`)
2. socat fork-mode invocation for concurrent CTF connections
3. FLAG startup validation via entrypoint wrapper script
4. Read-only FS + tmpfs declaration pattern (runtime flag, not Dockerfile-only)
5. BuildKit `--output` artifact extraction for static builder

## Phase 1: Design

### Data Model

See [data-model.md](data-model.md).

### Contracts

See [contracts/](contracts/).

### Quickstart

See [quickstart.md](quickstart.md).

## Implementation Notes

### Security invariants (all service images)

1. **No secrets in layers**: FLAG is never an `ARG` or `ENV` in service Dockerfiles — only read at runtime by the process.
2. **Startup validation**: Each service image entrypoint script checks `[ -z "$FLAG" ]` and exits 1 with a message (not revealing the value) before starting the service.
3. **No stdout flag leak**: Example apps return the flag only through the intended exploit path. Log lines MUST NOT print the FLAG value.
4. **uid=1000**: All `USER` directives and `COPY --chown` use uid 1000.
5. **PodSecurityStandards restricted compatibility**: No `CAP_*` adds, no `privileged`, no host paths, no setuid binaries.

### Image sizing targets

| Image | Base | Target size |
|-------|------|-------------|
| web   | python:3.11-alpine | < 80 MB |
| pwn   | ubuntu:22.04 | < 120 MB |
| misc  | python:3.11-alpine | < 60 MB |
| static | python:3.11-alpine (build only) | artifact only, no runtime image |

### socat fork mode

Pwn and misc images use socat with `-T60` (60s connection timeout) and `fork` to give each connecting player an isolated child process. Connection limit per pod is bounded by the 128 Mi RAM ceiling.

### Static builder output

Uses BuildKit `--output type=local,dest=./dist`. The Dockerfile's final stage COPYs `challenge.zip` to `/out/`, and the `--output` flag extracts `/out/` to `./dist/` on the host.
