# Contract: push-challenge.sh & setup-docr.sh CLI

**Feature**: 004-base-images-docr | **Date**: 2026-03-25

---

## push-challenge.sh

**Location**: `scripts/push-challenge.sh`

### Synopsis

```
./push-challenge.sh <image-name> <dockerfile-dir> [tag]
```

### Arguments

| Position | Name | Required | Validation | Description |
|----------|------|----------|------------|-------------|
| 1 | `image-name` | YES | `[a-zA-Z0-9][a-zA-Z0-9._-]*` | Image name component of the registry path |
| 2 | `dockerfile-dir` | YES | Must be an existing directory | Path to directory containing the Dockerfile |
| 3 | `tag` | NO | `[a-zA-Z0-9][a-zA-Z0-9._-]*`; defaults to `latest` | Image tag |

### Behaviour

1. Validate arguments — exit 1 with usage message if `image-name` or `dockerfile-dir` missing or invalid.
2. Build image: `docker build -t <full-ref> <dockerfile-dir>`
3. Push image: `docker push <full-ref>`
4. Print success message with full registry path on stdout.
5. Exit 0 on success; exit non-zero on any failure (build or push error).

### Full Registry Reference Produced

```
registry.digitalocean.com/infodays-registry/<image-name>:<tag>
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success — image built and pushed |
| 1 | Invalid arguments or validation failure |
| 2 | Docker build failed |
| 3 | Docker push failed (includes auth failure) |

### Prerequisites

- `docker` CLI available.
- `doctl registry login` previously run (via `setup-docr.sh`).
- Active internet connection to DOCR endpoint.

### Example

```sh
./push-challenge.sh base-web challenges/base-images/web
# Pushes: registry.digitalocean.com/infodays-registry/base-web:latest

./push-challenge.sh web-sqli challenges/web-sqli v1.2
# Pushes: registry.digitalocean.com/infodays-registry/web-sqli:v1.2
```

---

## setup-docr.sh

**Location**: `scripts/setup-docr.sh`

### Synopsis

```
./setup-docr.sh
```

### Arguments

None.

### Behaviour

1. Run `doctl registry login` — authenticates Docker daemon to DOCR.
2. Verify DOKS↔DOCR integration is active (check that the cluster can pull from the registry without image pull secrets).
3. Print status messages to stdout.
4. Exit 0 if both steps succeed; exit 1 with a clear error message if either fails.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | DOCR login successful and DOKS integration active |
| 1 | `doctl` not found, auth failed, or DOKS integration not active |

### Prerequisites

- `doctl` CLI installed and authenticated (`doctl auth init` previously run).
- DigitalOcean token has registry read/write permissions.
- DOKS cluster `infodays-ctf` exists (provisioned in Phase 1).
