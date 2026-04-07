# Contract: Static Challenge Archive Builder Interface

**Feature**: 004-base-images-docr | **Date**: 2026-03-25 | **Updated**: 2026-04-07

---

## Overview

Static challenges are file-download challenges with no running service. Players download a zip file from the CTFd challenge page and find the flag inside.

Two deployment methods:
1. **Automated** (recommended): `deploy-challenge.sh` builds the zip, uploads it, and creates the flag
2. **Manual**: Build with Docker, upload to CTFd Files section manually

## Automated Deployment (via deploy-challenge.sh)

### Manifest

```yaml
id: misc-welcome
name: "Welcome"
category: misc
type: static
description: "Download the file and find the flag."
# Optional dynamic scoring overrides (defaults: 500/50/25):
# initial: 500
# minimum: 50
# decay: 25
```

No `image` or `port` fields needed — `type: static` signals the deploy script to use the file-download path.

### Deploy Command

```bash
CTFD_URL=https://ctfd.infodays.net \
CTFD_ADMIN_TOKEN=<token> \
CTF_MASTER_SECRET=<secret> \
bash scripts/deploy-challenge.sh challenges/manifests/misc-welcome.yaml
```

### What the Deploy Script Does

1. Creates the challenge in CTFd (dynamic scoring, `type: dynamic`)
2. Derives the flag: `HMAC-SHA256(CTF_MASTER_SECRET, "static:{challenge_id}")[:32]` → `infodays{...}`
3. Builds `challenge.zip` containing `flag.txt` (+ any custom content)
4. Uploads zip to CTFd via `POST /api/v1/files` as a challenge attachment
5. Creates a static flag in CTFd via `POST /api/v1/flags`

**Skipped steps** (vs service challenges): no ConfigMap update, no controller restart, no bulk_spawn, no import_flags.

### Custom Challenge Content

To include additional files (challenge binaries, pcaps, images, etc.) alongside `flag.txt`:

```
challenges/static-content/{challenge_id}/
├── suspicious.pcap
├── memory.dmp
└── README.txt
```

The deploy script copies all files from this directory into the zip, then adds `flag.txt` with the derived flag.

### Flag Derivation

| Field | Value |
|-------|-------|
| Formula | `HMAC-SHA256(CTF_MASTER_SECRET, "static:{challenge_id}")` |
| Truncation | First 32 hex characters |
| Format | `infodays{<32 hex chars>}` |
| Scope | Same flag for all teams (not team-derived) |
| CTFd flag type | `static` (built-in CTFd type, not custom `team` type) |

### Dynamic Scoring

| Field | Default | Description |
|-------|---------|-------------|
| `initial` | 500 | Starting/maximum points |
| `minimum` | 50 | Floor points (never goes below this) |
| `decay` | 25 | Number of solves to reach the minimum |

All challenges (static and service) use CTFd dynamic scoring. Override per-manifest with `initial`, `minimum`, `decay` fields.

### Plugin UI Behaviour

The CTFd plugin **does not show Start/Stop buttons** for static challenges. When the controller status API doesn't include a challenge (no K8s Deployment exists), the plugin hides its UI entirely. CTFd's native file download link is displayed instead.

---

## Manual Build (Docker)

The static builder Dockerfile can also be used standalone:

### Build Command

```sh
docker buildx build \
  --build-arg FLAG="infodays{...}" \
  --output type=local,dest=./dist \
  challenges/base-images/static/
```

### Build Arguments

| Argument | Required | Validation | Description |
|----------|----------|------------|-------------|
| `FLAG` | **YES** | Non-empty string | The flag to embed in the archive. Build fails with a clear error if absent or empty. |

### Output

| Path | Description |
|------|-------------|
| `./dist/challenge.zip` | The challenge archive, ready for upload to CTFd Files section |

### Archive Structure

```
challenge.zip
└── flag.txt          ← Contains the flag value (the FLAG build argument)
```

`flag.txt` MUST be at the zip root.

### Failure Modes

| Condition | Behaviour |
|-----------|-----------|
| `FLAG` build-arg missing | Build exits non-zero with message: `"ERROR: FLAG build argument is required"` |
| `FLAG` build-arg is empty string | Build exits non-zero with the same error |

### No Runtime Image

The static builder MUST NOT produce a runnable container image. Its only output is the `./dist/challenge.zip` file on the host. The final Dockerfile stage uses `FROM scratch` to ensure no image can be accidentally pushed or deployed.
