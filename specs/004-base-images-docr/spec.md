# Feature Specification: Challenge Base Images & DOCR

**Feature Branch**: `004-base-images-docr`
**Created**: 2026-03-25
**Status**: Draft
**Input**: User description: "Read Plan.md and create a specification for Phase 4 — Challenge Base Images & DOCR."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Challenge Author Builds & Pushes a Web Challenge (Priority: P1)

A CTF challenge author wants to package a web-based challenge (e.g., a login form vulnerable to SQL injection) into a container image and push it to the shared registry so it can be deployed to the cluster.

**Why this priority**: Web challenges are the most common category; the web base image is the reference template all other authors will pattern-match against. Without a working web base image, authors cannot deliver any web challenges.

**Independent Test**: Author can build the web base image locally, run it, verify the `/flag` route behaves correctly, then push it to the registry using the push script — all without any other base image existing.

**Acceptance Scenarios**:

1. **Given** the web Dockerfile and example app exist, **When** the author runs `docker build`, **Then** the image builds without errors in two stages and the final image contains no build tools.
2. **Given** the built web image is running with `FLAG=infodays{test}`, **When** a player sends a valid SQL injection payload to the login form, **Then** the `/flag` route returns `infodays{test}`.
3. **Given** the built web image is running, **When** the container is inspected, **Then** the process runs as uid 1000 (non-root), the filesystem is read-only, and `/tmp` is a writable tmpfs.
4. **Given** a built image, **When** the author runs `push-challenge.sh base-web challenges/base-images/web`, **Then** the image is tagged and pushed to `registry.digitalocean.com/infodays-registry/base-web:latest` successfully.

---

### User Story 2 - Challenge Author Builds & Pushes a Pwn Challenge (Priority: P2)

A CTF challenge author wants to package a binary exploitation (pwn) challenge — a vulnerable C binary served over a raw TCP socket — and push it to the registry.

**Why this priority**: Pwn challenges are the second most common category and require a fundamentally different base (Ubuntu 22.04, compiled C binary, socat TCP listener).

**Independent Test**: Author builds the pwn image, connects via `nc` to port 1337, exploits the buffer overflow, and receives the flag — independent of all other images.

**Acceptance Scenarios**:

1. **Given** the pwn Dockerfile and `vuln.c` exist, **When** the author builds the image, **Then** `vuln.c` is compiled with stack protections disabled and no compiler toolchain remains in the final image.
2. **Given** the pwn image is running with `FLAG=infodays{pwn}`, **When** a player connects to port 1337 and sends an exploit payload that triggers the buffer overflow, **Then** the binary prints `infodays{pwn}`.
3. **Given** the running pwn container is inspected, **When** the running user is checked, **Then** socat and the binary run as uid 1000.

---

### User Story 3 - Challenge Author Builds & Pushes a Misc TCP Challenge (Priority: P3)

A challenge author packages a multi-step netcat riddle (misc category) into a container and pushes it to the registry.

**Why this priority**: Misc challenges round out the challenge library; they share the Alpine + Python pattern but use a different port and interaction model.

**Independent Test**: Author builds the misc image, connects to port 4444, answers all riddle steps correctly, and receives the flag.

**Acceptance Scenarios**:

1. **Given** the misc Dockerfile and `puzzle.py` exist, **When** the author builds the image, **Then** the image runs a TCP listener on port 4444.
2. **Given** the misc image is running with `FLAG=infodays{misc}`, **When** a player connects and provides all correct answers to the riddle steps, **Then** the script returns `infodays{misc}`.
3. **Given** a wrong answer at any step, **When** sent by a player, **Then** the connection is closed or an error is returned without leaking the flag.

---

### User Story 4 - Challenge Author Produces a Static Challenge Archive (Priority: P4)

A challenge author needs to produce a downloadable `.zip` archive for a static challenge (no running service), with the flag baked into the artifact at build time.

**Why this priority**: Static challenges (steganography, forensics, crypto with provided files) do not need a live pod; the flag is fixed and embedded in the artifact. This builder is used less frequently and does not depend on the other images.

**Independent Test**: Author runs `docker build --build-arg FLAG="infodays{static}" -o ./dist .` and a `challenge.zip` appears in `./dist` containing the correct flag.

**Acceptance Scenarios**:

1. **Given** the static Dockerfile and a sample artifact, **When** the author builds with `--build-arg FLAG="infodays{static}"`, **Then** `./dist/challenge.zip` is produced.
2. **Given** the produced zip is extracted, **When** its contents are inspected, **Then** `flag.txt` exists at the zip root and contains the flag `infodays{static}`.
3. **Given** the build runs without the `FLAG` build argument, **Then** the build fails with a clear error indicating the FLAG argument is required.

---

### User Story 5 - Challenge Author Sets Up DOCR Access (Priority: P5)

A new challenge author (or CI system) needs to authenticate against the DigitalOcean Container Registry and verify the DOKS ↔ DOCR integration before pushing any images.

**Why this priority**: A prerequisite to all push operations; covered by a one-time setup script that is simpler than the image workflows.

**Independent Test**: Author runs `setup-docr.sh` and the script exits 0, confirming registry login and DOKS integration.

**Acceptance Scenarios**:

1. **Given** valid DigitalOcean credentials, **When** the author runs `setup-docr.sh`, **Then** the script authenticates to DOCR and confirms the DOKS ↔ DOCR integration is active.
2. **Given** missing or invalid credentials, **When** `setup-docr.sh` is run, **Then** the script exits non-zero with a clear error message.

---

### Edge Cases

- What happens when `FLAG` is not set or is an empty string at container runtime? The service MUST refuse to start and exit with a clear error message; an empty-string FLAG is treated as equivalent to unset.
- What happens if `push-challenge.sh` is run before `doctl registry login`? The script must exit with a meaningful error rather than a cryptic daemon error.
- What happens if a challenge author passes a tag containing special characters? The script must validate or reject invalid tag values.
- How does the web challenge handle concurrent requests during a CTF? The example app is a reference only; the base image must not crash under light concurrent load.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a web challenge base image that serves a web application on port 80 with a `/flag` route protected by an SQL injection vulnerability, returning the flag only after a successful bypass.
- **FR-002**: The system MUST provide a pwn challenge base image that runs a TCP listener on port 1337 forwarding connections to a compiled C binary vulnerable to stack buffer overflow, which prints the flag after a successful exploit. The listener MUST support multiple simultaneous connections, each in an isolated process instance.
- **FR-003**: The system MUST provide a misc challenge base image that runs a TCP listener on port 4444 forwarding connections to a Python riddle script, which returns the flag after all correct answers. The listener MUST support multiple simultaneous connections, each in an isolated process instance.
- **FR-004**: The system MUST provide a static challenge archive builder that produces a `challenge.zip` artifact when given a `FLAG` build argument, and MUST fail the build if `FLAG` is not supplied. The zip MUST contain `flag.txt` at its root with the flag as its content.
- **FR-005**: All three service base images (web, pwn, misc) MUST run their processes as uid 1000 (non-root).
- **FR-006**: All three service base images (web, misc, pwn) MUST use multi-stage builds so that no build tools or package managers are present in the final runtime layer.
- **FR-007**: The web and misc base images MUST mount `/tmp` as a writable tmpfs and enforce a read-only root filesystem. The pwn image is exempt and MAY use a writable filesystem to support socat's fork sockets and binary runtime behaviour.
- **FR-008**: All service images MUST read the flag exclusively from the `FLAG` environment variable at runtime; the flag MUST NOT be baked into any service image layer. If `FLAG` is unset or an empty string, the container MUST refuse to start and exit with a clear error message.
- **FR-009**: The system MUST provide a `push-challenge.sh` script that accepts an image name, a Dockerfile directory, and an optional tag; builds the image; and pushes it to `registry.digitalocean.com/infodays-registry/<image-name>:<tag>`.
- **FR-010**: The `push-challenge.sh` script MUST default the tag to `latest` when no tag argument is provided.
- **FR-011**: The system MUST provide a `setup-docr.sh` script that authenticates to DOCR and verifies the DOKS ↔ DOCR integration is active.
- **FR-012**: All pushed base images MUST be pullable from a pod running in the `challenges` namespace without additional image pull credentials.

### Key Entities

- **Base Image**: A versioned container image stored in DOCR representing a challenge category template (web, pwn, misc, static). Key attributes: registry path, tag, challenge category, exposed port.
- **Challenge Archive**: A `.zip` file produced at build time containing static challenge assets with the flag embedded. Not a running service.
- **FLAG**: A secret string in `infodays{...}` format. Injected at runtime via Kubernetes Secret for service challenges; supplied as a build argument for static challenges only.
- **Push Script**: A shell script that encapsulates the build → tag → push workflow for challenge authors.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All four base images (web, pwn, misc, static) build from a clean environment without errors in a single build invocation each.
- **SC-002**: Each service image correctly returns the expected flag after a valid exploit or correct player interaction, verified by a smoke test.
- **SC-003**: No service image layer contains the flag value; scanning image layers for `infodays{` returns zero matches.
- **SC-004**: A challenge author with no prior knowledge of the registry can authenticate and push a test image end-to-end using only `setup-docr.sh` and `push-challenge.sh`.
- **SC-005**: All three service images, when deployed as pods in the `challenges` namespace, are pullable without image pull secret configuration.
- **SC-006**: Each service image runs its process as a non-root user, confirmed by inspection of the running container.

## Clarifications

### Session 2026-03-25

- Q: Should the pwn and misc images also enforce a read-only root filesystem? → A: Read-only FS on web + misc; pwn exempt (writable FS permitted for socat fork sockets and binary runtime).
- Q: Should the pwn image use a multi-stage build to remove the compiler from the final layer? → A: Yes — multi-stage required for all three service images; no build tools in any final runtime layer.
- Q: Should service images (pwn, misc) support multiple simultaneous player connections? → A: Yes — fork mode; each player gets an isolated process instance.
- Q: Should an empty-string FLAG be treated the same as unset at container startup? → A: Yes — both unset and empty-string FLAG must cause the container to refuse to start with a clear error.
- Q: Where inside challenge.zip should the flag be embedded for static challenges? → A: `flag.txt` at the zip root.

## Assumptions

- `doctl` is installed and configured on the challenge author's machine; the push and setup scripts do not install it.
- The DigitalOcean Container Registry (`infodays-registry`) and the DOKS cluster (`infodays-ctf`) already exist (provisioned in Phase 1).
- The `challenges` namespace already has DOCR pull access via the DOKS ↔ DOCR integration configured in earlier phases.
- The example app in the web image and the riddle in the misc image are minimal working demonstrations for authors, not final challenge content.
- The pwn binary is compiled inside the Docker build; a local C toolchain on the author's machine is not required.
- Flag format is `infodays{...}`; the scripts and images do not validate format, only pass it through.

## Out of Scope

- Actual puzzle content beyond minimal working examples (SQL injection form, buffer overflow binary, netcat riddle).
- Flag generation or flag rotation tooling.
- CI/CD automation for building and pushing base images.
- Image vulnerability scanning or signing.
- Challenge-specific customisation guides beyond inline script comments.
