# Contract: Static Challenge Archive & Per-Team Download

**Feature**: 004-base-images-docr | **Date**: 2026-03-25 | **Updated**: 2026-04-07

---

## Overview

Static challenges are file-download challenges with no running service. Players download a zip file from the challenge modal and find the flag inside.

Each team receives a **unique zip** with a team-derived HMAC flag — the same formula used for service challenges. Zips are generated **on the fly** by the CTFd plugin's `/download/{challenge_id}` endpoint, not pre-built or stored.

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
2. Updates the `challenge-manifests` ConfigMap (so `import_flags.py` picks up the manifest)
3. Restarts the controller API (to reload manifest cache)
4. Runs `import_flags.py` to create a `team` flag row in CTFd

**Skipped steps** (vs service challenges): no bulk_spawn (no K8s pods). No zip generation or file upload — the plugin generates zips on the fly.

### Custom Challenge Content

To include additional files (challenge binaries, pcaps, images, etc.) alongside `flag.txt`:

```
challenges/static-content/{challenge_id}/
├── suspicious.pcap
├── memory.dmp
└── README.txt
```

The plugin's download endpoint includes all files from this directory in the zip, then adds/overwrites `flag.txt` with the team-derived flag.

### Flag Derivation

| Field | Value |
|-------|-------|
| Formula | `HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")` |
| Truncation | First 32 hex characters |
| Format | `infodays{<32 hex chars>}` |
| Scope | **Per-team** — each team gets a unique flag (same formula as service challenges) |
| CTFd flag type | `team` (custom type — same as service challenges, not built-in `static`) |
| Cheater detection | Yes — cross-team flag submission is detected and logged |

### Dynamic Scoring

| Field | Default | Description |
|-------|---------|-------------|
| `initial` | 500 | Starting/maximum points |
| `minimum` | 50 | Floor points (never goes below this) |
| `decay` | 25 | Number of solves to reach the minimum |

All challenges (static and service) use CTFd dynamic scoring. Override per-manifest with `initial`, `minimum`, `decay` fields.

### Plugin Download Endpoint

The CTFd plugin exposes `GET /download/<challenge_manifest_id>`:

1. Authenticates the user via `get_current_user()` / `get_current_team()`
2. Derives the flag: `_derive(team.id, challenge_manifest_id, CTF_MASTER_SECRET)`
3. Builds a zip in memory containing `flag.txt` (+ custom content if present)
4. Returns the zip as `{challenge_manifest_id}.zip` with `Content-Disposition: attachment`

No zips are stored on disk — each download is generated fresh from the team's HMAC.

### Plugin UI Behaviour

The CTFd plugin **shows a "Download Challenge" button** for static challenges. When the controller status API doesn't include a challenge (no K8s Deployment exists), the plugin renders a download button pointing to `/download/{challenge_id}` instead of the Start/Stop controls.

---

## Manual Build (Docker)

The static builder Dockerfile can also be used standalone for testing:

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
| `./dist/challenge.zip` | The challenge archive (for manual testing only — production uses on-the-fly generation) |

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
