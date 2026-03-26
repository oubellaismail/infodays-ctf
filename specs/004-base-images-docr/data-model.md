# Data Model: Challenge Base Images & DOCR

**Phase**: 1 | **Date**: 2026-03-25 | **Feature**: 004-base-images-docr

This feature produces container images and shell scripts, not a database-backed service. The "data model" describes the entities, their attributes, and the relationships between them as they exist in the registry, filesystem, and runtime.

---

## Entities

### BaseImage

A versioned OCI container image stored in DOCR, representing one challenge category template.

| Attribute | Type | Constraint | Description |
|-----------|------|------------|-------------|
| `registry_path` | string | MUST match `registry.digitalocean.com/infodays-registry/<id>:<tag>` | Full pullable image reference |
| `challenge_id` | string | One of: `base-web`, `base-pwn`, `base-misc` | Short identifier used as image name |
| `tag` | string | Default: `latest`; alphanumeric + `-` + `.` only | Image version tag |
| `category` | enum | `web` \| `pwn` \| `misc` | Challenge category |
| `exposed_port` | integer | `80` (web), `1337` (pwn), `4444` (misc) | TCP port the container listens on |
| `run_as_uid` | integer | Must be `1000` | Non-root user in the runtime stage |
| `read_only_fs` | boolean | `true` for web + misc; `false` for pwn | Whether container supports read-only root FS |
| `multi_stage` | boolean | Always `true` | Multi-stage build with no build tools in final layer |

**State**: BaseImages are immutable once pushed. Tags may be overwritten (latest); versioned tags are append-only.

---

### ChallengeArchive

A `.zip` artifact produced by the static builder, containing challenge files for upload to CTFd.

| Attribute | Type | Constraint | Description |
|-----------|------|------------|-------------|
| `filename` | string | Always `challenge.zip` | Output artifact name |
| `output_path` | string | `./dist/challenge.zip` relative to build dir | Host path after extraction |
| `flag_file` | string | `flag.txt` at zip root | Location of the flag inside the archive |
| `flag_value` | string | `infodays{...}` format; set at build time via `--build-arg FLAG=` | The flag embedded in the artifact |

**Lifecycle**: Produced once per `docker buildx build` invocation. Not stored in DOCR (build-only artifact). Uploaded manually to CTFd Files section.

---

### FLAG (Runtime Secret)

The secret string injected into service-challenge pods at runtime.

| Attribute | Type | Constraint | Description |
|-----------|------|------------|-------------|
| `value` | string | Non-empty; format `infodays{...}` | The flag value |
| `source` | enum | `K8s Secret env var` (service) \| `Docker build ARG` (static) | How the flag reaches the image |
| `env_var_name` | string | Always `FLAG` | The environment variable name in service images |
| `build_arg_name` | string | Always `FLAG` | The Docker build argument name in static builder |

**Security invariants**:
- `FLAG` value MUST NOT appear in any image layer for service images.
- `FLAG` value MUST NOT be printed to stdout or logs; only returned through the intended exploit path.
- `FLAG` is validated at startup: empty string or unset → container exits 1.

---

### PushScript

The `push-challenge.sh` shell script; encapsulates the build→tag→push workflow.

| Attribute | Type | Constraint | Description |
|-----------|------|------------|-------------|
| `image_name` | string (positional arg 1) | Required; alphanumeric + `-` only | Image name (used as `<image-name>` in registry path) |
| `dockerfile_dir` | string (positional arg 2) | Required; must be a valid directory path | Directory containing the Dockerfile |
| `tag` | string (positional arg 3) | Optional; defaults to `latest` | Image version tag |
| `registry_prefix` | string | Hardcoded: `registry.digitalocean.com/infodays-registry` | Target registry |

**Full registry path produced**: `registry.digitalocean.com/infodays-registry/<image_name>:<tag>`

**Prerequisites**: `doctl` authenticated, `doctl registry login` completed (via `setup-docr.sh`).

---

### SetupScript

The `setup-docr.sh` shell script; one-time authentication and integration verification.

| Attribute | Type | Description |
|-----------|------|-------------|
| `exit_code` | integer | `0` = success, `1` = failure (auth or integration not active) |
| `operations` | sequence | 1. `doctl registry login`; 2. verify DOKS↔DOCR integration |

---

## Relationships

```
BaseImage
  ├── built from → Dockerfile (web/, pwn/, misc/)
  ├── pushed via → PushScript
  └── receives at runtime → FLAG (via K8s Secret)

ChallengeArchive
  ├── built from → Dockerfile (static/)
  └── contains → FLAG (baked in via build ARG)

PushScript
  └── requires → SetupScript (doctl registry login must have run)
```

---

## Validation Rules

| Entity | Rule | Error |
|--------|------|-------|
| BaseImage at runtime | FLAG must be non-empty | Container exits 1 with error to stderr |
| BaseImage build | No FLAG ARG/ENV in Dockerfile | Build lint / review check |
| ChallengeArchive build | FLAG build-arg must be non-empty | `docker build` exits non-zero |
| PushScript invocation | image_name and dockerfile_dir must be provided | Script exits 1 with usage message |
| PushScript tag | Must match `[a-zA-Z0-9][a-zA-Z0-9._-]*` | Script exits 1 with validation error |
