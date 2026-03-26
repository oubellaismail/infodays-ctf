# Tasks: Challenge Base Images & DOCR

**Input**: Design documents from `/specs/004-base-images-docr/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Organization**: Tasks grouped by user story. No tests (not requested). Each task is fully self-contained — all implementation details are embedded in the task description so no additional context is needed.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared dependencies)
- **[Story]**: Which user story this task belongs to

## Key Constants (reference for all tasks)

```
Registry prefix : registry.digitalocean.com/infodays-registry
Non-root UID    : 1000
Flag env var    : FLAG  (runtime, never a Dockerfile ARG/ENV for service images)
Flag format     : infodays{...}
Entrypoint rule : validate FLAG is non-empty → exit 1 to stderr if not → exec service
```

---

## Phase 1: Setup

**Purpose**: Create all required directories so subsequent tasks can write files directly.

- [x] T001 Create directory tree: `mkdir -p challenges/base-images/web challenges/base-images/pwn challenges/base-images/misc challenges/base-images/static` (all four leaf dirs must exist before any other task)

**Checkpoint**: `ls challenges/base-images/` shows `web/ pwn/ misc/ static/`

---

## Phase 2: Foundational

**Purpose**: No shared source code exists across images, but the FLAG-validation entrypoint pattern is identical for all three service images. Document it here so Phase 3–5 tasks can reference it by name ("the standard entrypoint pattern") without re-deriving it.

**Standard entrypoint pattern** (used verbatim in web, pwn, and misc images):

```sh
#!/bin/sh
set -e
if [ -z "${FLAG}" ]; then
  echo "ERROR: FLAG environment variable is required and must not be empty." >&2
  exit 1
fi
exec "$@"
```

- The script is saved as `entrypoint.sh` in each image's directory.
- `chmod +x` must be applied before `COPY` in the Dockerfile.
- `ENTRYPOINT ["/entrypoint.sh"]` and `CMD [...]` are separate directives.
- `exec "$@"` passes CMD arguments to the entrypoint so the service becomes PID 1.

- [x] T002 Confirm understanding: no files to create in this phase — read the standard entrypoint pattern above and verify it is referenced correctly in T003, T007, T011.

**Checkpoint**: Pattern understood. Phases 3–5 reference it explicitly.

---

## Phase 3: User Story 1 — Web Challenge Base Image (Priority: P1) 🎯 MVP

**Goal**: A multi-stage Docker image that serves a Flask login page (vulnerable to SQL injection) on port 80. The `/flag` route returns the `FLAG` env var only after a successful SQLi bypass. Runs as uid 1000, read-only root FS, writable /tmp.

**Independent Test**:
```sh
docker build -t base-web:local challenges/base-images/web/
# Must succeed with no errors

docker run --rm -e FLAG="infodays{test}" -p 8080:80 base-web:local &
sleep 2
curl -s http://localhost:8080/         # must return HTTP 200 (login page)
curl -s -c /tmp/c.txt -b /tmp/c.txt \
     -d "username=' OR '1'='1&password=x" \
     http://localhost:8080/login        # must redirect or return 200
curl -s -c /tmp/c.txt -b /tmp/c.txt \
     http://localhost:8080/flag         # must return "infodays{test}"

docker run --rm base-web:local          # no FLAG set → must exit 1 with error on stderr
docker run --rm -e FLAG="" base-web:local  # empty FLAG → same error

docker inspect $(docker create base-web:local) \
  --format '{{.Config.User}}'           # must be "1000"
```

### Implementation for User Story 1

- [x] T003 [US1] Create `challenges/base-images/web/entrypoint.sh` using the standard entrypoint pattern from Phase 2 exactly (no changes). File must be executable (`chmod +x`).

- [x] T004 [US1] Create `challenges/base-images/web/app.py` — a Flask application with the following behaviour:
  - **Imports**: `flask`, `sqlite3`, `os`
  - **Database**: Create an in-memory SQLite database on startup with a `users` table containing one row: `username='admin', password='s3cr3t'`. Recreate it each process start.
  - **`GET /`**: Render an HTML login form (inline string, no template file needed) with fields `username` and `password` (POST to `/login`). Return HTTP 200.
  - **`POST /login`**: Build the SQL query as a **string concatenation** (intentionally vulnerable): `"SELECT * FROM users WHERE username='" + username + "' AND password='" + password + "'"`. Execute it. If any row is returned, set a session cookie `logged_in=true` and redirect to `/flag`. If no row, return the login form with the message "Invalid credentials." Do **not** use parameterised queries — the SQLi must work.
  - **`GET /flag`**: If session cookie `logged_in=true`, return plain text `os.environ['FLAG']`. Otherwise, return HTTP 403 with body "Forbidden."
  - **Secret key**: `app.secret_key = os.urandom(24)` (regenerated each start — session cookies are invalidated on restart, which is acceptable for a CTF image).
  - **Run**: `app.run(host='0.0.0.0', port=80)` only when `__name__ == '__main__'`. The Dockerfile will invoke via `python app.py`, not gunicorn.
  - **No logging of FLAG value** anywhere in the file.

- [x] T005 [US1] Create `challenges/base-images/web/Dockerfile` as a two-stage build:

  **Stage 1 — builder** (`FROM python:3.11-alpine AS builder`):
  ```
  WORKDIR /install
  COPY requirements.txt .     ← create a requirements.txt with just "flask" before this line
  RUN pip install --prefix=/install/deps --no-cache-dir -r requirements.txt
  ```

  **Stage 2 — runtime** (`FROM python:3.11-alpine`):
  ```
  # Copy installed packages from builder
  COPY --from=builder /install/deps /usr/local

  # Create non-root user
  RUN adduser -D -u 1000 appuser

  # Create /tmp with sticky bit (required for read-only FS at runtime)
  RUN mkdir -p /tmp && chmod 1777 /tmp

  # Copy app files owned by uid 1000
  WORKDIR /app
  COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh
  COPY --chown=1000:1000 app.py .

  USER 1000
  EXPOSE 80
  ENTRYPOINT ["/entrypoint.sh"]
  CMD ["python", "app.py"]
  ```

  Also create `challenges/base-images/web/requirements.txt` containing exactly one line: `flask`

**Checkpoint**: `docker build -t base-web:local challenges/base-images/web/` succeeds. Web story independently functional.

---

## Phase 4: User Story 2 — Pwn Challenge Base Image (Priority: P2)

**Goal**: A multi-stage Docker image on Ubuntu 22.04 that serves a C binary via socat on port 1337. The binary is vulnerable to a stack buffer overflow; after exploitation it prints the `FLAG` env var. Runs as uid 1000. Multi-stage build (no gcc in final layer). Writable root FS (pwn is exempt from read-only FS constraint).

**Independent Test**:
```sh
docker build -t base-pwn:local challenges/base-images/pwn/
# Must succeed with no errors

docker run --rm -e FLAG="infodays{pwn}" -p 1337:1337 base-pwn:local &
sleep 2
python3 -c "
import socket, time
s = socket.socket()
s.connect(('localhost', 1337))
print(s.recv(1024).decode())           # must print 'Enter your name:'
payload = b'A' * 64 + b'\xef\xbe\xad\xde'  # 64 bytes overflow + magic value
s.send(payload + b'\n')
time.sleep(0.2)
print(s.recv(1024).decode())           # must include 'infodays{pwn}'
s.close()
"

docker run --rm base-pwn:local          # no FLAG → exit 1 with error on stderr

# Verify no gcc in final image
docker run --rm base-pwn:local which gcc 2>&1  # must exit non-zero (not found)
```

### Implementation for User Story 2

- [x] T006 [US2] Create `challenges/base-images/pwn/entrypoint.sh` using the standard entrypoint pattern from Phase 2 exactly. File must be executable.

- [x] T007 [US2] Create `challenges/base-images/pwn/vuln.c` — a C program with the following behaviour:
  - **Buffer overflow vulnerability**: A function `vuln()` that declares `char buf[64]` on the stack and reads from stdin with `gets(buf)` (or `read(STDIN_FILENO, buf, 256)` — either works, the point is reading more bytes than the buffer holds).
  - **Magic value check**: After the read, check if a local variable (placed on the stack after `buf`) equals `0xdeadbeef`. If it does, print `"You win! Flag: "` followed by `getenv("FLAG")` followed by a newline, then exit 0.
  - **Normal path**: Print `"Enter your name: "` to stdout (flushed), read input, print `"Hello, <name>!"` and exit 0.
  - **`main()`**: Calls `vuln()`. No other logic needed.
  - **Important**: Use `setvbuf(stdout, NULL, _IONBF, 0)` at the start of `main` to disable buffering (required for socat interaction).
  - **No logging of FLAG value** except through the win condition output.

  The binary will be compiled with: `gcc -fno-stack-protector -z execstack -no-pie -o vuln vuln.c`

- [x] T008 [US2] Create `challenges/base-images/pwn/Dockerfile` as a two-stage build:

  **Stage 1 — builder** (`FROM ubuntu:22.04 AS builder`):
  ```
  ENV DEBIAN_FRONTEND=noninteractive
  RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && \
      rm -rf /var/lib/apt/lists/*
  WORKDIR /build
  COPY vuln.c .
  RUN gcc -fno-stack-protector -z execstack -no-pie -o vuln vuln.c
  ```

  **Stage 2 — runtime** (`FROM ubuntu:22.04`):
  ```
  ENV DEBIAN_FRONTEND=noninteractive
  RUN apt-get update && apt-get install -y --no-install-recommends socat && \
      rm -rf /var/lib/apt/lists/*

  # Create non-root user
  RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -M appuser

  # Copy binary and entrypoint
  COPY --from=builder --chown=1000:1000 /build/vuln /usr/local/bin/vuln
  COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh

  USER 1000
  EXPOSE 1337
  ENTRYPOINT ["/entrypoint.sh"]
  CMD ["socat", "-T60", "TCP-LISTEN:1337,reuseaddr,fork", "EXEC:/usr/local/bin/vuln,nofork"]
  ```

**Checkpoint**: `docker build -t base-pwn:local challenges/base-images/pwn/` succeeds. `docker run --rm base-pwn:local which gcc` returns non-zero (gcc absent). Pwn story independently functional.

---

## Phase 5: User Story 3 — Misc TCP Challenge Base Image (Priority: P3)

**Goal**: A multi-stage Docker image (Alpine + Python 3.11) that serves a multi-step TCP riddle via socat on port 4444. Returns `FLAG` env var only after all correct answers. Runs as uid 1000, read-only root FS, writable /tmp.

**Independent Test**:
```sh
docker build -t base-misc:local challenges/base-images/misc/
# Must succeed

docker run --rm -e FLAG="infodays{misc}" -p 4444:4444 base-misc:local &
sleep 2

# Correct answers (must return flag)
python3 -c "
import socket, time
s = socket.socket()
s.connect(('localhost', 4444))
print(s.recv(1024).decode())   # first question
s.send(b'42\n')
time.sleep(0.1)
print(s.recv(1024).decode())   # second question
s.send(b'blue\n')
time.sleep(0.1)
out = s.recv(1024).decode()
print(out)
assert 'infodays{misc}' in out, 'Flag not found!'
s.close()
"

# Wrong answer (must NOT return flag, must close connection)
python3 -c "
import socket
s = socket.socket()
s.connect(('localhost', 4444))
s.recv(1024)
s.send(b'wrong\n')
import time; time.sleep(0.2)
data = s.recv(1024).decode()
assert 'infodays' not in data, 'Flag leaked on wrong answer!'
print('OK: no flag leaked')
s.close()
"

docker run --rm base-misc:local          # no FLAG → exit 1 on stderr
```

### Implementation for User Story 3

- [x] T009 [US3] Create `challenges/base-images/misc/entrypoint.sh` using the standard entrypoint pattern from Phase 2 exactly. File must be executable.

- [x] T010 [US3] Create `challenges/base-images/misc/puzzle.py` — a Python script that:
  - **Reads FLAG** from `os.environ['FLAG']` at the top of the script (not validated here — entrypoint handles that).
  - **Uses `sys.stdout` line-buffered** mode: add `sys.stdout = open(sys.stdout.fileno(), 'w', buffering=1)` at the start (required for socat interaction without guessing at flushes).
  - **Step 1**: Print `"Question 1: What is the answer to life, the universe, and everything? "` (no newline), read one line from stdin. Strip whitespace. If the answer is `"42"`, proceed to step 2. Otherwise, print `"Wrong answer. Goodbye."` and `sys.exit(1)`.
  - **Step 2**: Print `"Question 2: What colour is the sky? "` (no newline), read one line from stdin. Strip and lowercase. If the answer is `"blue"`, print `"Correct! Here is your flag: " + FLAG` followed by a newline, then `sys.exit(0)`. Otherwise, print `"Wrong answer. Goodbye."` and `sys.exit(1)`.
  - **No logging of FLAG** except through the win-condition print.

- [x] T011 [US3] Create `challenges/base-images/misc/Dockerfile` as a two-stage build:

  **Stage 1 — builder** (`FROM python:3.11-alpine AS builder`):
  ```
  WORKDIR /install
  RUN pip install --prefix=/install/deps --no-cache-dir socat 2>/dev/null || true
  # Note: socat is a system package, not a pip package.
  # Builder stage here has nothing to install for misc.
  # Keep stage to match pattern; it is a no-op for misc.
  ```

  Actually: misc has no pip dependencies beyond stdlib. The "builder" stage exists only to satisfy the multi-stage requirement and future extensibility. Simplify:

  **Stage 1 — builder** (`FROM python:3.11-alpine AS builder`):
  ```
  # No pip deps for misc — builder is a placeholder for future extensibility
  RUN echo "builder stage"
  ```

  **Stage 2 — runtime** (`FROM python:3.11-alpine`):
  ```
  # Install socat (system package)
  RUN apk add --no-cache socat

  # Create non-root user
  RUN adduser -D -u 1000 appuser

  # Create /tmp with sticky bit (required for read-only FS at runtime)
  RUN mkdir -p /tmp && chmod 1777 /tmp

  # Copy files
  WORKDIR /app
  COPY --chown=1000:1000 entrypoint.sh /entrypoint.sh
  COPY --chown=1000:1000 puzzle.py .

  USER 1000
  EXPOSE 4444
  ENTRYPOINT ["/entrypoint.sh"]
  CMD ["socat", "-T60", "TCP-LISTEN:4444,reuseaddr,fork", "EXEC:python3 /app/puzzle.py,nofork"]
  ```

**Checkpoint**: `docker build -t base-misc:local challenges/base-images/misc/` succeeds. Misc story independently functional.

---

## Phase 6: User Story 4 — Static Challenge Archive Builder (Priority: P4)

**Goal**: A build-only Dockerfile that uses BuildKit `--output` to produce `./dist/challenge.zip` on the host. The zip contains `flag.txt` at its root with the `FLAG` build argument as content. No runtime image is produced.

**Independent Test**:
```sh
docker buildx build \
  --build-arg FLAG="infodays{static_test}" \
  --output type=local,dest=./dist \
  challenges/base-images/static/
# Must succeed

unzip -p ./dist/challenge.zip flag.txt
# Must output: infodays{static_test}

# Missing FLAG must fail
docker buildx build \
  --output type=local,dest=./dist \
  challenges/base-images/static/ 2>&1 | grep -i "ERROR"
# Must show error about missing FLAG
```

### Implementation for User Story 4

- [x] T012 [US4] Create `challenges/base-images/static/Dockerfile` — a two-stage BuildKit file:

  **Stage 1 — builder** (`FROM python:3.11-alpine AS builder`):
  ```
  ARG FLAG
  # Validate FLAG is non-empty at build time
  RUN test -n "${FLAG}" || \
      (echo "ERROR: FLAG build argument is required and must not be empty." >&2 && exit 1)

  RUN apk add --no-cache zip

  WORKDIR /build
  # Write flag.txt
  RUN echo -n "${FLAG}" > flag.txt
  # Create the archive with flag.txt at the zip root
  RUN zip challenge.zip flag.txt
  # Copy artifact to /out/
  RUN mkdir -p /out && cp challenge.zip /out/
  ```

  **Stage 2 — export** (`FROM scratch`):
  ```
  # Export /out contents to the host via --output type=local,dest=./dist
  COPY --from=builder /out /
  ```

  **Usage comment** (add as a Dockerfile comment at the top):
  ```
  # Build: docker buildx build --build-arg FLAG="infodays{...}" --output type=local,dest=./dist .
  # Output: ./dist/challenge.zip  (contains flag.txt at zip root)
  # This Dockerfile produces NO runtime image.
  ```

**Checkpoint**: `./dist/challenge.zip` produced after `docker buildx build --build-arg FLAG="infodays{test}" --output type=local,dest=./dist challenges/base-images/static/`. `unzip -p ./dist/challenge.zip flag.txt` returns `infodays{test}`. Static story independently functional.

---

## Phase 7: User Story 5 — DOCR Scripts (Priority: P5)

**Goal**: Two shell scripts — `setup-docr.sh` (authenticates to DOCR + verifies DOKS integration) and `push-challenge.sh` (build → tag → push wrapper).

**Independent Test**:
```sh
# Argument validation (no auth needed)
bash scripts/push-challenge.sh 2>&1 | grep -i "usage"   # missing args → usage message

bash scripts/push-challenge.sh "bad name!" path/ 2>&1 | grep -i "invalid"  # bad image name

bash scripts/push-challenge.sh myimage nonexistent-dir/ 2>&1 | grep -i "not.*dir"

# Full end-to-end (requires doctl auth + DOCR access):
bash scripts/setup-docr.sh
bash scripts/push-challenge.sh base-web challenges/base-images/web latest
```

### Implementation for User Story 5

- [x] T013 [P] [US5] Create `scripts/setup-docr.sh`:

  ```sh
  #!/usr/bin/env bash
  set -euo pipefail

  # 1. Verify doctl is available
  if ! command -v doctl &>/dev/null; then
    echo "ERROR: doctl is not installed or not in PATH." >&2
    exit 1
  fi

  # 2. Authenticate Docker daemon to DOCR
  echo "Logging in to registry.digitalocean.com..."
  doctl registry login

  # 3. Verify DOKS <-> DOCR integration
  echo "Verifying DOKS <-> DOCR integration..."
  # The integration is active if the cluster has the registry secret in its kube-system namespace.
  # Use doctl to check; exit 1 with a clear message if inactive.
  REGISTRY_NAME=$(doctl registry get --format Name --no-header 2>/dev/null || true)
  if [ -z "${REGISTRY_NAME}" ]; then
    echo "ERROR: No DOCR registry found. Ensure infodays-registry is provisioned." >&2
    exit 1
  fi

  INTEGRATION=$(doctl kubernetes cluster registry list --format ClusterUUID,RegistryName --no-header 2>/dev/null || true)
  if [ -z "${INTEGRATION}" ]; then
    echo "ERROR: DOKS <-> DOCR integration is not active." >&2
    echo "Run: doctl kubernetes cluster registry add <cluster-id> to enable it." >&2
    exit 1
  fi

  echo "DOKS <-> DOCR integration: active"
  echo "Setup complete. You can now run push-challenge.sh."
  ```

  Make the file executable with `chmod +x`.

- [x] T014 [P] [US5] Create `scripts/push-challenge.sh`:

  ```sh
  #!/usr/bin/env bash
  set -euo pipefail

  REGISTRY="registry.digitalocean.com/infodays-registry"

  usage() {
    echo "Usage: $0 <image-name> <dockerfile-dir> [tag]" >&2
    echo "  image-name     : alphanumeric, hyphens, dots only" >&2
    echo "  dockerfile-dir : directory containing Dockerfile" >&2
    echo "  tag            : image tag (default: latest)" >&2
    exit 1
  }

  # Validate required args
  if [ $# -lt 2 ]; then
    usage
  fi

  IMAGE_NAME="$1"
  DOCKERFILE_DIR="$2"
  TAG="${3:-latest}"

  # Validate image name (alphanumeric, hyphens, dots — no spaces or special chars)
  if ! echo "${IMAGE_NAME}" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'; then
    echo "ERROR: Invalid image name '${IMAGE_NAME}'. Use alphanumeric characters, hyphens, or dots only." >&2
    exit 1
  fi

  # Validate tag
  if ! echo "${TAG}" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'; then
    echo "ERROR: Invalid tag '${TAG}'. Use alphanumeric characters, hyphens, or dots only." >&2
    exit 1
  fi

  # Validate dockerfile directory exists
  if [ ! -d "${DOCKERFILE_DIR}" ]; then
    echo "ERROR: '${DOCKERFILE_DIR}' is not a directory." >&2
    exit 1
  fi

  FULL_REF="${REGISTRY}/${IMAGE_NAME}:${TAG}"

  echo "Building ${FULL_REF} from ${DOCKERFILE_DIR} ..."
  docker build -t "${FULL_REF}" "${DOCKERFILE_DIR}" || { echo "ERROR: docker build failed." >&2; exit 2; }

  echo "Pushing ${FULL_REF} ..."
  docker push "${FULL_REF}" || { echo "ERROR: docker push failed. Run setup-docr.sh first." >&2; exit 3; }

  echo "Pushed: ${FULL_REF}"
  ```

  Make the file executable with `chmod +x`.

**Checkpoint**: `bash scripts/push-challenge.sh 2>&1 | grep -i usage` returns the usage message. Script story independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Security verification across all images, edge-case smoke tests, and final validation against the quickstart.

- [x] T015 [P] Verify no FLAG in web image layers: `docker history --no-trunc base-web:local | grep -i infodays` must return empty. If any output: the Dockerfile has a bug — `FLAG` was baked in as an ARG or ENV. Fix `challenges/base-images/web/Dockerfile`.

- [x] T016 [P] Verify no FLAG in pwn image layers: same check for `base-pwn:local`.

- [x] T017 [P] Verify no FLAG in misc image layers: same check for `base-misc:local`.

- [x] T018 [P] Verify all service images reject empty FLAG: run each image with `-e FLAG=""` and confirm exit code is non-zero and stderr contains "ERROR: FLAG".

- [x] T019 Validate web image security context: `docker inspect $(docker create base-web:local) --format '{{.Config.User}}'` must output `1000`. Confirm `readOnlyRootFilesystem` is NOT enforced in the image itself (it is a K8s deployment concern per research.md — the image must not hardcode it).

- [x] T020 Validate static builder produces no runnable image: `docker buildx build --build-arg FLAG="x" challenges/base-images/static/` WITHOUT `--output` should build without error but produce no tagged image and no `FROM scratch` runtime container.

- [x] T021 Run the full quickstart.md validation sequence from `specs/004-base-images-docr/quickstart.md` steps 1–5 and confirm all steps pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Informational only — no files created, no blockers
- **US1 Web (Phase 3)**: Depends on Phase 1 only
- **US2 Pwn (Phase 4)**: Depends on Phase 1 only — independent of US1
- **US3 Misc (Phase 5)**: Depends on Phase 1 only — independent of US1, US2
- **US4 Static (Phase 6)**: Depends on Phase 1 only — fully independent
- **US5 Scripts (Phase 7)**: Depends on Phase 1 only — T013 and T014 are parallel
- **Polish (Phase 8)**: Depends on Phases 3–7 complete (needs images built)

### User Story Dependencies

- **US1 (P1)**: After Phase 1 — no dependency on other stories
- **US2 (P2)**: After Phase 1 — no dependency on other stories
- **US3 (P3)**: After Phase 1 — no dependency on other stories
- **US4 (P4)**: After Phase 1 — no dependency on other stories
- **US5 (P5)**: After Phase 1 — T013 and T014 are parallel within the story

### Within Each Story

- entrypoint.sh → Dockerfile (entrypoint.sh must exist before Dockerfile references it)
- app source file (app.py / vuln.c / puzzle.py) → Dockerfile (same reason)
- requirements.txt (web only) → Dockerfile

### Parallel Opportunities

- Phases 3, 4, 5, 6, 7 can all run in parallel after Phase 1
- T013 and T014 (setup-docr.sh and push-challenge.sh) are parallel within Phase 7
- T015–T020 in Phase 8 are all parallel (each checks a different image)

---

## Parallel Execution Example: All Stories at Once

```bash
# After Phase 1 (T001) completes, all five stories can be implemented in parallel:

# Terminal A — US1 Web
# T003 → T004 → T005 (must be sequential within US1: entrypoint.sh before Dockerfile)

# Terminal B — US2 Pwn
# T006 → T007 → T008

# Terminal C — US3 Misc
# T009 → T010 → T011

# Terminal D — US4 Static
# T012 (only one file)

# Terminal E — US5 Scripts
# T013 and T014 in parallel (different files)
```

---

## Implementation Strategy

### MVP First (US1 only)

1. T001 (setup)
2. T003 → T004 → T005 (web image)
3. Validate web checkpoint
4. Done — fully functional web base image, independently deployable

### Incremental Delivery

1. T001 → T003–T005 → web ✅
2. T006–T008 → pwn ✅
3. T009–T011 → misc ✅
4. T012 → static ✅
5. T013–T014 → scripts ✅
6. T015–T021 → validation ✅

### Single Developer Sequence

T001 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012 → T013 → T014 → T015–T021

---

## Notes

- [P] tasks = different files, no shared dependencies, safe to run in parallel
- [Story] label maps each task to a user story for traceability
- Each service image has exactly three files: `entrypoint.sh`, source file, `Dockerfile`
- The static builder has exactly one file: `Dockerfile`
- No test files are generated (not requested)
- `challenges/base-images/web/requirements.txt` is created as part of T005 (Dockerfile task)
- Read-only FS is NOT enforced in any Dockerfile — it is enforced in K8s `securityContext` at deployment time (see research.md topic 4 and contracts/image-runtime-interface.md)
- FLAG is NEVER a Dockerfile `ARG` or `ENV` for service images — only for the static builder as a build-time `ARG`
