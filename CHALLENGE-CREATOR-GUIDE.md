# INFODAYS CTF — Challenge Creator Guide

This guide covers everything you need to create, package, and deploy a challenge for the INFODAYS CTF infrastructure.

---

## Table of Contents

1. [How the System Works](#how-the-system-works)
2. [Challenge Types](#challenge-types)
3. [Step 1 — Write Your Challenge Manifest](#step-1--write-your-challenge-manifest)
4. [Step 2 — Write Your Dockerfile](#step-2--write-your-dockerfile)
5. [Step 3 — Flags](#step-3--flags)
6. [Step 4 — Static Files (type: static only)](#step-4--static-files-type-static-only)
7. [Step 5 — Build and Push Your Image](#step-5--build-and-push-your-image)
8. [Step 6 — Deploy](#step-6--deploy)
9. [Manifest Field Reference](#manifest-field-reference)
10. [Naming Rules](#naming-rules)
11. [Scoring Reference](#scoring-reference)
12. [Base Image Reference](#base-image-reference)
13. [Common Mistakes](#common-mistakes)

---

## How the System Works

Each challenge runs as a **per-team Kubernetes pod**. When a player clicks "Start Challenge" in CTFd, the controller spins up their team's dedicated container. The flag is unique per team — it is injected into the pod as an environment variable (`FLAG`) and computed from an HMAC formula at deploy time.

**You never hardcode flags.** You read `os.environ['FLAG']` (Python) or `getenv("FLAG")` (C). The infrastructure handles the rest.

---

## Challenge Types

| Type | Use for | Access method | Port |
|---|---|---|---|
| `http` | Web challenges (HTTP app) | Browser via `http://challenges.infodays.net:{port}` | 8080 |
| `tcp` | Pwn / Misc with socat | `nc challenges.infodays.net {port}` | 1337 (pwn) or 4444 (misc) |
| `static` | Forensics / Crypto / OSINT / Reversing — file download only | Player downloads a zip from CTFd | N/A |

> Static challenges have **no running container**. The flag is embedded in a per-team zip generated on the fly.

---

## Step 1 — Write Your Challenge Manifest

Create a file at `challenges/manifests/{id}.yaml`.

### Service challenge (http or tcp)

```yaml
id: web-scout-database          # lowercase, hyphenated — MUST match CTFd name when slugified
name: "Scout Database"          # CTFd display name — slug must equal id (see Naming Rules)
category: Web                   # Web | Pwn | Misc | Crypto | Forensics | Reversing | OSINT
image: registry.digitalocean.com/infodays-registry/challenges:scout-database
port: 8080                      # Container port — 8080 (web), 1337 (pwn), 4444 (misc)
type: http                      # http or tcp
description: "Find the hidden data in the scout database."  # Optional
initial: 300                    # Optional — max points (default: 500)
minimum: 50                     # Optional — floor points (default: 50)
decay: 20                       # Optional — solves to reach minimum (default: 25)
```

### Static challenge (file download)

```yaml
id: forensics-vip-invitation
name: "VIP Invitation"
category: Forensics
type: static
description: "Someone leaked a VIP pass. What does it reveal?"
initial: 300
minimum: 45
decay: 15
```

### Multi-flag challenge

Some challenges award multiple flags (e.g., user → root escalation). Each sub-flag becomes a separate CTFd challenge entry:

```yaml
id: misc-referee-briefing
name: "Referee Briefing"
category: Misc
description: "A TCP service hosting a referee briefing session. Two flags await — find the first, then escalate."
image: registry.digitalocean.com/infodays-registry/challenges:referee-briefing
port: 4444
type: tcp
run_as_root: true                  # Required if challenge uses root-only paths or SUID
allow_privilege_escalation: true   # Required for SUID exploits (GTFOBins etc.)
flags:
  - id: referee-briefing-1
    name: "Referee Briefing — Part 1"
    category: Misc
    env: USER_FLAG                 # Env var name injected into the container
    initial: 250
    minimum: 35
    decay: 20
  - id: referee-briefing-2
    name: "Referee Briefing — Part 2"
    category: Misc
    env: ROOT_FLAG
    initial: 450
    minimum: 65
    decay: 15
```

> When `flags:` is present, the top-level `id` drives resource naming; each entry gets its own CTFd challenge and HMAC-derived flag injected under its `env` variable name.

---

## Step 2 — Write Your Dockerfile

Use the base images in `challenges/base-images/` as starting points. **Always read `FLAG` from the environment — never hardcode it.**

### Web (HTTP, port 8080)

```dockerfile
FROM python:3.11-alpine AS builder
WORKDIR /install
COPY requirements.txt .
RUN pip install --prefix=/install/deps --no-cache-dir -r requirements.txt

FROM python:3.11-alpine
COPY --from=builder /install/deps /usr/local
RUN adduser -D -u 1000 appuser
RUN mkdir -p /tmp && chmod 1777 /tmp
WORKDIR /app
COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh
COPY --chown=1000:1000 app.py .
USER 1000
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "app.py"]
```

`entrypoint.sh` — validates the FLAG env var is set before starting:

```sh
#!/bin/sh
set -e
if [ -z "${FLAG}" ]; then
  echo "ERROR: FLAG environment variable is required." >&2
  exit 1
fi
exec "$@"
```

`app.py` minimal pattern — read flag from env:

```python
import os
from flask import Flask
app = Flask(__name__)

@app.route('/flag')
def get_flag():
    # Only return after your challenge condition is met
    return os.environ['FLAG']

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

### Pwn (TCP socat, port 1337)

```dockerfile
FROM ubuntu:22.04 AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY vuln.c .
RUN gcc -fno-stack-protector -z execstack -no-pie -o vuln vuln.c

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -M appuser
COPY --from=builder --chown=1000:1000 /build/vuln /usr/local/bin/vuln
COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh
USER 1000
EXPOSE 1337
ENTRYPOINT ["/entrypoint.sh"]
CMD ["socat", "-T60", "TCP-LISTEN:1337,reuseaddr,fork", "EXEC:/usr/local/bin/vuln,nofork"]
```

`vuln.c` minimal pattern:

```c
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // Required — disables buffering for socat
    printf("Enter your name: ");
    // ... your vulnerable logic ...
    printf("You win! Flag: %s\n", getenv("FLAG"));
    return 0;
}
```

> `setvbuf(stdout, NULL, _IONBF, 0)` is **mandatory** in C — without it socat will hang waiting for a flushed buffer.

### Misc (TCP socat, port 4444)

```dockerfile
FROM python:3.11-alpine AS builder
# Reserve for pip deps if needed

FROM python:3.11-alpine
RUN apk add --no-cache socat
RUN adduser -D -u 1000 appuser
RUN mkdir -p /tmp && chmod 1777 /tmp
WORKDIR /app
COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh
COPY --chown=1000:1000 puzzle.py .
USER 1000
EXPOSE 4444
ENTRYPOINT ["/entrypoint.sh"]
CMD ["socat", "-T60", "TCP-LISTEN:4444,reuseaddr,fork", "EXEC:python3 /app/puzzle.py,nofork"]
```

`puzzle.py` minimal pattern:

```python
import sys
import os

# REQUIRED — line-buffered stdout for socat compatibility
sys.stdout = open(sys.stdout.fileno(), 'w', buffering=1)

FLAG = os.environ['FLAG']

sys.stdout.write("Your puzzle question here: ")
answer = sys.stdin.readline().strip()

if answer == "correct_answer":
    print(f"Correct! {FLAG}")
else:
    print("Wrong answer. Goodbye.")
```

> `buffering=1` on stdout is **mandatory** in Python socat challenges — without it output is silently dropped.

### Static (no runtime image — file download only)

Static challenges produce a `challenge.zip` artifact, not a running container. The zip is generated on the fly by the plugin per team; **you do not build a Docker image for static challenges**.

Place any extra files you want included in the player's download at:

```
challenges/static-content/{challenge-id}/
```

Example for `forensics-vip-invitation`:

```
challenges/static-content/vip-invitation/
└── invitation.eml          ← your forensics file
```

The plugin will package `flag.txt` (unique per team) + all your files into a single zip on demand.

---

## Step 3 — Flags

**You never generate or hardcode flags.** The system derives every flag automatically.

### Formula

```
flag = infodays{ HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32] }
```

- `CTF_MASTER_SECRET` — a shared secret set at deploy time (stored in the controller's K8s secret)
- `team_id` — CTFd team ID (integer, assigned at registration)
- `challenge_id` — the `id` field from your manifest (e.g., `web-scout-database`)

### What you do

1. In your code, read `os.environ['FLAG']` (Python) or `getenv("FLAG")` (C).
2. Return it only when the challenge condition is satisfied.
3. That's it. The controller injects the correct HMAC-derived value for each team at pod start.

### Multi-flag challenges

If your manifest has a `flags:` list, each entry's `env` field is the env var name injected:

```python
import os
user_flag = os.environ['USER_FLAG']
root_flag = os.environ['ROOT_FLAG']
```

---

## Step 4 — Static Files (type: static only)

Skip this step if your challenge is `http` or `tcp`.

1. Create the directory: `challenges/static-content/{id}/`
2. Put your challenge files there (e.g., a `.pcap`, `.eml`, `.exe`, `.pdf`).
3. `flag.txt` is added automatically per team — do not include it yourself.

The player downloads a zip named `{challenge-id}.zip` containing your files plus their unique `flag.txt`.

---

## Step 5 — Build and Push Your Image

Skip this step for `type: static` challenges.

```bash
# Tag format: registry.digitalocean.com/infodays-registry/challenges:{challenge-id}
bash scripts/push-challenge.sh {challenge-id} challenges/real/challenges/{category}/{challenge-id}

# Example:
bash scripts/push-challenge.sh scout-database challenges/real/challenges/web/scout-database
```

Your image must be pushed to DOCR before deploying. The manifest `image:` field must match exactly:

```
registry.digitalocean.com/infodays-registry/challenges:{challenge-id}
```

---

## Step 6 — Deploy

```bash
export CTFD_URL=https://ctfd.infodays.net
export CTFD_ADMIN_TOKEN=<token>
export CTF_MASTER_SECRET=<secret>

bash scripts/deploy-challenge.sh challenges/manifests/{id}.yaml
```

This single command:
1. Creates the CTFd challenge entry (with dynamic scoring)
2. Updates the controller ConfigMap
3. Runs `bulk_spawn` — creates per-team K8s Deployments (replicas=0) + Services
4. Runs `import_flags` — pushes per-team HMAC flags to CTFd
5. (Static) — skips K8s steps, only creates CTFd entry + imports flags

---

## Manifest Field Reference

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | Yes | string | Unique ID — lowercase, hyphenated (e.g., `web-sqli`) |
| `name` | Yes | string | CTFd display name — slug must equal `id` (see Naming Rules) |
| `category` | Yes | string | `Web` / `Pwn` / `Misc` / `Crypto` / `Forensics` / `Reversing` / `OSINT` |
| `type` | Yes | string | `http` / `tcp` / `static` |
| `image` | http/tcp only | string | Full DOCR image reference |
| `port` | http/tcp only | int | Container port (`8080` / `1337` / `4444`) |
| `description` | No | string | Shown in CTFd modal (defaults to `"Challenge: {name}"`) |
| `memory_limit` | No | string | K8s memory limit override (default: `128Mi`) |
| `initial` | No | int | Max points at zero solves (default: `500`) |
| `minimum` | No | int | Floor points (default: `50`) |
| `decay` | No | int | Solves to reach minimum (default: `25`) |
| `run_as_root` | No | bool | Run container as root — needed if challenge writes to `/root/` |
| `allow_privilege_escalation` | No | bool | Set `allowPrivilegeEscalation: true` — needed for SUID exploits |
| `flags` | No | list | Sub-flags for multi-part challenges (see Multi-flag section) |

---

## Naming Rules

The manifest `name` field, when slugified, **must exactly equal** the `id` field.

Slugification rule:
```
name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")
```

| `id` | Required `name` |
|---|---|
| `web-scout-database` | `"Scout Database"` |
| `misc-referee-briefing` | `"Referee Briefing"` |
| `forensics-vip-invitation` | `"VIP Invitation"` |
| `pwn-shanks` | `"Shanks"` |

A mismatch causes the plugin to derive the wrong challenge ID, breaking flag validation and the Start/Stop buttons.

---

## Scoring Reference

All challenges use **dynamic scoring** — points start at `initial` and decrease as more teams solve it, reaching `minimum` after `decay` solves.

Suggested starting values by difficulty:

| Difficulty | `initial` | `minimum` | `decay` |
|---|---|---|---|
| Easy | 100–300 | 25–50 | 20–25 |
| Medium | 300–500 | 50–75 | 15–20 |
| Hard | 500–700 | 75–100 | 10–15 |
| Expert | 700–1500 | 100–250 | 5–10 |

---

## Base Image Reference

| Category | Base image | Port | Protocol | File to edit |
|---|---|---|---|---|
| Web | `challenges/base-images/web/` | 8080 | HTTP (Flask) | `app.py` |
| Pwn | `challenges/base-images/pwn/` | 1337 | TCP (socat) | `vuln.c` |
| Misc | `challenges/base-images/misc/` | 4444 | TCP (socat) | `puzzle.py` |
| Crypto | `challenges/base-images/crypto/` | 8080 | HTTP (Flask) | `app.py` |
| Forensics | `challenges/base-images/forensics/` | 8080 | HTTP (Flask) | `app.py` |
| Reversing | `challenges/base-images/reversing/` | 1337 | TCP (socat) | `check.c` |
| OSINT | `challenges/base-images/osint/` | 4444 | TCP (socat) | `challenge.py` |
| Static | `challenges/base-images/static/` | N/A | Download | Put files in `static-content/` |

---

## Common Mistakes

### Flag not reading from environment

```python
# WRONG
FLAG = "infodays{hardcoded_flag_here}"

# CORRECT
FLAG = os.environ['FLAG']
```

### stdout not flushed (socat TCP challenges)

```python
# WRONG — output silently dropped
print("Enter answer: ")

# CORRECT — line buffered
sys.stdout = open(sys.stdout.fileno(), 'w', buffering=1)
```

```c
// WRONG — output buffered, socat hangs
printf("Enter your name: ");

// CORRECT — unbuffered
setvbuf(stdout, NULL, _IONBF, 0);
printf("Enter your name: ");
```

### Name/ID mismatch

```yaml
# WRONG — "Web Scout DB" slugifies to "web-scout-db", not "web-scout-database"
id: web-scout-database
name: "Web Scout DB"

# CORRECT
id: web-scout-database
name: "Scout Database"
```

### Wrong port for type

```yaml
# WRONG
type: tcp
port: 8080   # 8080 is for http, not tcp pwn

# CORRECT for pwn
type: tcp
port: 1337
```

### Including flag.txt in static content

The plugin generates `flag.txt` automatically per team. If you include your own `flag.txt` in `challenges/static-content/{id}/`, it will be overwritten. Use a different filename for any hint files.

### Building an image for a static challenge

`type: static` challenges have no container. Do not build or push a Docker image for them. Just put your files in `challenges/static-content/{id}/` and write the manifest.
