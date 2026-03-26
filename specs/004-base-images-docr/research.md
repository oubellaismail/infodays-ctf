# Research: Challenge Base Images & DOCR

**Phase**: 0 | **Date**: 2026-03-25 | **Feature**: 004-base-images-docr

## 1. Multi-Stage Ubuntu Build for Pwn Image

**Decision**: Two-stage Dockerfile — builder stage uses `gcc` on `ubuntu:22.04` to compile the C binary; runtime stage starts from a clean `ubuntu:22.04` and installs only `socat` + copies the compiled binary.

**Rationale**: Multi-stage separation removes gcc, make, and build headers from the final image. This satisfies Constitution Principle II (no package managers in final layers) and reduces the image attack surface. Ubuntu is required (rather than Alpine) because CTF pwn challenges commonly depend on glibc behaviour for exploit development; Alpine uses musl which changes stack layout and offsets.

**Runtime-stage minimal package set**:
- `socat` (TCP listener)
- `libc6` (already present in base; needed for dynamically-linked binary)
- Nothing else — `apt-get` cache cleared in the same `RUN` layer

**Alternatives considered**:
- Static binary with `-static` flag → eliminates libc dependency but changes binary layout in ways that alter the expected exploit; rejected for the reference example.
- `google/distroless` base → no shell available, complicates entrypoint validation script; rejected.
- Alpine + musl → incompatible glibc-dependent exploit patterns; rejected for pwn.

---

## 2. socat Fork Mode for Concurrent Connections

**Decision**: `socat TCP-LISTEN:<PORT>,reuseaddr,fork EXEC:/usr/local/bin/entrypoint.sh`

**Rationale**: The `fork` keyword causes socat to spawn a new child process for each incoming TCP connection, giving every player an isolated memory space. `reuseaddr` allows the container to restart quickly without "address already in use" errors. This is the canonical CTF TCP challenge pattern used across nearly all major CTF platforms.

**Connection timeout**: Add `-T60` to close idle connections after 60 seconds, preventing resource exhaustion within the 128 Mi pod RAM budget.

**Full invocation**: `socat -T60 TCP-LISTEN:<PORT>,reuseaddr,fork EXEC:/usr/local/bin/challenge,nofork`

**Alternatives considered**:
- `xinetd` → heavier, requires config file, adds daemon overhead; rejected.
- Binary with built-in `fork()` → couples challenge logic to concurrency management; rejected for template simplicity.
- Single connection (no `fork`) → blocks all other players while one is connected; rejected (violates FR-002/FR-003).

---

## 3. FLAG Startup Validation (Entrypoint Script)

**Decision**: Each service image ships an `entrypoint.sh` that validates `FLAG` before starting the service. Checks both unset and empty-string cases. Exits 1 with an error to stderr (not stdout) if invalid.

**Canonical pattern**:
```sh
#!/bin/sh
set -e
if [ -z "${FLAG}" ]; then
  echo "ERROR: FLAG environment variable is required and must not be empty." >&2
  exit 1
fi
exec "$@"
```

The message intentionally does not print the FLAG value. `exec "$@"` replaces the shell with the main process so PID 1 is the service (proper signal handling for K8s).

**Rationale**: Fail-fast prevents a pod from entering a running-but-broken state where players receive an empty flag. Errors go to stderr so they appear in `kubectl logs` without polluting stdout. `exec` ensures SIGTERM from K8s reaches the process directly.

**Alternatives considered**:
- Bash `${FLAG:?message}` shorthand → terse but less readable for maintainers; acceptable alternative.
- K8s `required` field on env var → enforces presence at Deployment level, not at container startup; doesn't protect against empty string; rejected as sole mechanism.

---

## 4. Read-Only Root Filesystem + /tmp tmpfs

**Decision**: Enforce `readOnlyRootFilesystem: true` in the K8s pod `securityContext`, combined with an `emptyDir` volume (in-memory) mounted at `/tmp`. The Dockerfile creates `/tmp` with `chmod 1777` so the mount point exists with correct permissions.

**Dockerfile responsibility** (web + misc images only):
```dockerfile
RUN mkdir -p /tmp && chmod 1777 /tmp
```

**K8s responsibility** (in the challenge Deployment manifest — Phase 5/6 work):
```yaml
securityContext:
  readOnlyRootFilesystem: true
volumeMounts:
- name: tmp
  mountPath: /tmp
volumes:
- name: tmp
  emptyDir:
    medium: Memory
    sizeLimit: 32Mi
```

**Rationale**: `readOnlyRootFilesystem` is a runtime/deployment concern, not a build concern. `VOLUME /tmp` in a Dockerfile is NOT equivalent — it creates a bind-mount at runtime but does not enforce read-only root. The Dockerfile can only ensure the directory exists with the right mode; enforcement is at the K8s level. The pwn image is exempt (clarification Q1) because socat's fork mode may write temporary socket files.

**Alternatives considered**:
- `VOLUME /tmp` in Dockerfile → common misconception; does not enforce read-only FS; rejected.
- Leaving /tmp absent from Dockerfile → mount will fail if the directory doesn't exist in the image; rejected.

---

## 5. BuildKit --output for Static Archive Extraction

**Decision**: Use `docker buildx build --output type=local,dest=./dist .` with a final `FROM scratch` stage that copies only the artifact directory from the builder.

**Dockerfile pattern**:
```dockerfile
FROM python:3.11-alpine AS builder
ARG FLAG
RUN test -n "${FLAG}" || (echo "ERROR: FLAG build argument is required" >&2 && exit 1)
WORKDIR /build
COPY . .
RUN python3 build.py "${FLAG}" && \
    mkdir -p /out && \
    cp challenge.zip /out/

FROM scratch
COPY --from=builder /out /
```

**Build command**:
```sh
docker buildx build \
  --build-arg FLAG="infodays{...}" \
  --output type=local,dest=./dist \
  .
# Produces: ./dist/challenge.zip
```

**FLAG validation**: Done via `RUN test -n "${FLAG}"` so the build fails immediately with a clear message if FLAG is absent. This differs from service images where FLAG is a runtime env var; here it is a build ARG because the flag is baked into the artifact.

**Rationale**: BuildKit local output type is the only way to extract a file from a build without creating a runnable image. The `FROM scratch` final stage acts as a "export manifest" — its entire rootfs (just `/challenge.zip`) is written to `./dist/`. This is the canonical pattern for Docker artifact generation (cross-platform compilers, documentation generators, etc.).

**Alternatives considered**:
- `docker run --rm -v ./dist:/out image` → requires a runnable image, adds unnecessary runtime layer; rejected.
- `docker cp` from a stopped container → more steps, less portable in CI; rejected.
- Named stage output: `--target=builder --output type=local` → exports full builder filesystem including source; not desired; rejected.
