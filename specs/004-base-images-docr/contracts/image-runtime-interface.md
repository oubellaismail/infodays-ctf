# Contract: Service Image Runtime Interface

**Feature**: 004-base-images-docr | **Date**: 2026-03-25

This contract defines the runtime interface for the three service base images (web, pwn, misc). Any Deployment manifest or K8s controller that provisions these images MUST honour these contracts.

---

## Web Challenge Base Image

**Registry path**: `registry.digitalocean.com/infodays-registry/base:web`

### Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FLAG` | **YES** | The flag string (`infodays{...}`). Non-empty. Container exits 1 if absent or empty. |

### Network

| Attribute | Value |
|-----------|-------|
| Exposed port | `8080/TCP` |
| Protocol | HTTP |

### Security Context (required at deployment)

| Setting | Value |
|---------|-------|
| `runAsUser` | `1000` |
| `runAsNonRoot` | `true` |
| `readOnlyRootFilesystem` | `true` |
| `/tmp` volume | `emptyDir` (in-memory, 32 Mi limit) |
| Capabilities | Drop ALL |

### Health Check

`GET /` returns HTTP 200. Use as liveness/readiness probe.

### Startup Behaviour

- Entrypoint validates `FLAG` is non-empty → exits 1 with error to stderr if not.
- Flask app starts on port 80.
- `/flag` route returns the flag only after a successful SQL injection bypass of the login form.

---

## Pwn Challenge Base Image

**Registry path**: `registry.digitalocean.com/infodays-registry/base:pwn`

### Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FLAG` | **YES** | The flag string (`infodays{...}`). Non-empty. Container exits 1 if absent or empty. |

### Network

| Attribute | Value |
|-----------|-------|
| Exposed port | `1337/TCP` |
| Protocol | Raw TCP |
| Concurrency | Fork mode — each connection gets an isolated child process |
| Idle timeout | 60 seconds |

### Security Context (required at deployment)

| Setting | Value |
|---------|-------|
| `runAsUser` | `1000` |
| `runAsNonRoot` | `true` |
| `readOnlyRootFilesystem` | `false` (pwn exempt — writable FS) |
| Capabilities | Drop ALL |

### Startup Behaviour

- Entrypoint validates `FLAG` is non-empty → exits 1 with error to stderr if not.
- socat starts in fork mode on port 1337, forwarding each connection to the compiled binary.
- Binary reads `FLAG` from environment and prints it after a successful buffer overflow exploit.
- Exploit: write 76 bytes to overflow `buf[64]`, then `\xef\xbe\xad\xde` (0xdeadbeef little-endian) to overwrite `magic`.

---

## Misc TCP Challenge Base Image

**Registry path**: `registry.digitalocean.com/infodays-registry/base:misc`

### Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FLAG` | **YES** | The flag string (`infodays{...}`). Non-empty. Container exits 1 if absent or empty. |

### Network

| Attribute | Value |
|-----------|-------|
| Exposed port | `4444/TCP` |
| Protocol | Raw TCP (line-oriented text) |
| Concurrency | Fork mode — each connection gets an isolated child process |
| Idle timeout | 60 seconds |

### Security Context (required at deployment)

| Setting | Value |
|---------|-------|
| `runAsUser` | `1000` |
| `runAsNonRoot` | `true` |
| `readOnlyRootFilesystem` | `true` |
| `/tmp` volume | `emptyDir` (in-memory, 32 Mi limit) |
| Capabilities | Drop ALL |

### Startup Behaviour

- Entrypoint validates `FLAG` is non-empty → exits 1 with error to stderr if not.
- socat starts in fork mode on port 4444, forwarding each connection to the Python riddle script.
- Script returns `FLAG` only after all riddle steps are answered correctly.
- Wrong answer → connection closed without leaking the flag.

---

## Common Constraints (all service images)

- `FLAG` MUST NOT appear in any image layer. Use `docker history --no-trunc` to verify.
- `FLAG` MUST NOT be printed to stdout or container logs under any circumstances.
- All service images MUST be compatible with Kubernetes `restricted` PodSecurityStandards.
- Resource limits at deployment: 0.5 CPU / 128 Mi RAM (Constitution Principle V).
