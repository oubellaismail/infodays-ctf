# Infodays CTF — Platform Status Report
**Date:** 2026-04-09
**Prepared by:** Platform Engineering
**Status:** Deployed and operational

---

## Executive Summary

The Infodays CTF platform is fully deployed and operational on DigitalOcean infrastructure. All core systems are running: the competition frontend (CTFd), the database layer, the challenge controller, and 1,750 pre-provisioned challenge instances across 50 teams and 35 challenges. The platform has been validated end-to-end with individual player accounts, per-team isolated flags, and a custom UI matching the event's visual identity.

---

## Infrastructure Overview

| Component | Technology | Status |
|---|---|---|
| Cloud Provider | DigitalOcean (region: fra1) | Active |
| Kubernetes Cluster | DOKS `infodays-ctf`, K8s v1.35.1 | Running |
| Worker Nodes | 4 × s-4vcpu-8gb (autoscale 3–5) | All Ready |
| Container Registry | DOCR `infodays-registry` | Active |
| Infrastructure-as-Code | Terraform ≥1.5, DO provider v2.x | Applied |

### Worker Nodes

| Node | Public IP | Status |
|---|---|---|
| infodays-workers-18i72 | 164.92.188.106 | Ready |
| infodays-workers-18i7p | 164.90.187.83 | Ready |
| infodays-workers-18i7t | 165.22.84.48 | Ready |
| infodays-workers-1uosg | 64.227.124.227 | Ready |

---

## DNS & Networking

| Hostname | Resolves To | Purpose |
|---|---|---|
| `ctfd.infodays.net` | 164.90.243.163 (nginx LB) | CTFd competition frontend |
| `challenges.infodays.net` | All 4 worker IPs (round-robin) | Challenge access (TCP + HTTP) |
| `*.challenges.infodays.net` | 164.90.243.163 (nginx LB) | Wildcard (reserved) |

**TLS:** `ctfd.infodays.net` has a valid Let's Encrypt certificate issued via DNS-01 (cert-manager + DigitalOcean DNS provider).

**Challenge access model:**
- Both TCP and HTTP challenges are accessed directly via `challenges.infodays.net:{nodeport}`
- TCP: `nc challenges.infodays.net <port>`
- HTTP: `http://challenges.infodays.net:<port>`
- No HTTPS or session cookie required — accessible with any standard tool

**Firewalls:**
- `ctf-challenges-nodeport-access`: Opens TCP 30000–32767 on all worker nodes to the internet
- DOKS-managed firewall: Opens 80/443 on the nginx load balancer

---

## Application Stack

All services are running in the `ctfd` Kubernetes namespace.

| Service | Replicas | Image | Status |
|---|---|---|---|
| CTFd (frontend) | 5 | ctfd/ctfd:latest | Running |
| MySQL Primary | 1 | mysql:8 (StatefulSet, 10Gi PVC) | Running |
| MySQL Replica | 1 | mysql:8 (StatefulSet, GTID replication) | Running |
| ProxySQL | 2 | proxysql:2.x (read/write split) | Running |
| Redis | 1 | redis:7-alpine (StatefulSet, 1Gi PVC, AOF) | Running |
| Controller API | 8 | (custom Python/FastAPI) | Running |
| Controller Daemon | 1 | (custom Python) | Running |

**CTFd is live at:** https://ctfd.infodays.net
**Health check:** https://ctfd.infodays.net/healthcheck → `OK`

### Resource Sizing (validated under 200-VU load)

| Component | CPU Request | Memory Limit | Notes |
|---|---|---|---|
| CTFd | 1000m × 5 replicas | 2Gi each | 4 gevent workers, Redis cache |
| MySQL Primary | — | 4Gi | max-connections=500, innodb buffer 512MB |
| MySQL Replica | — | 2Gi | Read-only, GTID replication |
| ProxySQL | — | — | 200 connections per backend |
| Controller API | 250m × 8 replicas | 1Gi each | 8 uvicorn workers, 5s status cache |
| Redis | — | — | AOF persistence, 1Gi PVC |

---

## Challenge Library

**36 challenges** across 7 categories, serving 50 teams.

| Category | Count | Type |
|---|---|---|
| Web | 5 | HTTP (browser) |
| Crypto | 5 | HTTP (browser) |
| Forensics | 5 | HTTP (browser) |
| Pwn | 5 | TCP (netcat) |
| Reversing | 5 | TCP (netcat) |
| Misc | 6 | TCP (netcat) + 1 static download |
| OSINT | 5 | TCP (netcat) |
| **Total** | **36** | |

### Challenge Types

| Type | Count | Access Method |
|---|---|---|
| HTTP | 15 | `http://challenges.infodays.net:<port>` |
| TCP | 20 | `nc challenges.infodays.net <port>` |
| Static (file download) | 1 | Download via CTFd UI |

### Scoring

All challenges use **dynamic scoring**:
- Starting value: **500 points**
- Minimum value: **50 points**
- Decay: value reaches minimum after **25 solves**

---

## Teams & Players

| Metric | Value |
|---|---|
| Teams | 50 |
| Players per team | 4 individual accounts |
| Total player accounts | 200 |
| Player mode | Individual logins, shared team identity |

Each team member has their own CTFd account and can log in independently. All 4 members see the same challenge state, solve progress, and score — CTFd natively resolves any player to their team.

**Account format:**
- Email: `{team-slug}-p{n}@infodays.net`
- Each team has players P1–P4
- First player (P1) is the team captain

---

## Challenge Infrastructure (Kubernetes)

| Metric | Value |
|---|---|
| Total Deployments (teams × challenges) | 1,750 |
| Total Services | 1,750 |
| tcp-services ConfigMap entries | 1,750 |
| Active pods at rest | 0 (all pre-provisioned at replicas=0) |

### How it works

1. **Pre-spawn** (`bulk_spawn.py`): All `team × challenge` Kubernetes resources (Deployment, Service, Secret) are created at `replicas=0` before the event. This means startup is near-instant when a player activates a challenge.

2. **On-demand activation** (Controller API): When a player clicks "Start" in the UI, the controller patches the deployment to `replicas=1`. The pod starts in seconds.

3. **Automatic shutdown** (Controller Daemon): The daemon polls every 5 minutes and scales down any deployment that has been running for more than 30 minutes without interaction.

4. **Pod cap**: Each team is limited to **4 active challenge instances** at once across all 4 players. This is enforced at the controller level, not CTFd.

### Per-team Flag Isolation

Each team receives a **unique flag** per challenge, derived from an HMAC:

```
flag = HMAC(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:32]
formatted = "infodays{<hex>}"
```

This makes flag sharing between teams detectable — submitting another team's flag is logged with the original team's identity.

---

## Security Model

### Network Isolation

| Layer | Mechanism |
|---|---|
| Cluster default | Kubernetes `default-deny-all` NetworkPolicy in both namespaces |
| Challenge ingress | Only ingress-nginx and direct NodePort traffic allowed into challenge pods |
| Challenge egress | Only DNS (port 53) allowed out — no internet access from challenge pods |
| CTFd egress | Allowlisted to MySQL/ProxySQL, Redis, Controller only |
| Controller K8s API access | CiliumNetworkPolicy `toEntities: kube-apiserver` |

### Flag Security

- Per-team HMAC flags — no shared flags
- Custom `team` flag type in CTFd — validates against the derived HMAC, not a stored plaintext flag
- Cheater detection: `submitting_user_id` is recorded alongside team_id on every solve, enabling identification of the specific player who submitted a cross-team flag

### Challenge Isolation

- **HTTP challenges**: No session required — port-based access. Isolation is cryptographic (unique flags per team).
- **TCP challenges**: Same model. `nc challenges.infodays.net <port>` — unique flag is injected as an env var at pod start.
- **Static challenges**: Per-team zip generated on-the-fly — each download includes a unique `flag.txt`.

---

## CTFd Plugin (Custom UI)

A custom CTFd plugin provides the challenge activation/deactivation interface.

**Features:**
- "Start" / "Stop" buttons injected into every challenge modal
- Real-time status indicator (fresh / starting / running / suspended)
- Displays the challenge URL (HTTP or nc command) once the instance is running
- "Download Challenge" button for static challenges
- Dark-mode themed UI (Inter + JetBrains Mono fonts, custom CSS token system)

**Tech stack:** Vanilla JS (no build step), Bootstrap 5, Flask Blueprint for static asset serving, Python proxy routes for controller API calls.

---

## Container Images

All challenge images are stored in the DigitalOcean Container Registry (`registry.digitalocean.com/infodays-registry`).

| Tag | Runtime | Purpose |
|---|---|---|
| `base:web` | Alpine + Python 3.11 + Flask | Web challenges (port 8080) |
| `base:pwn` | Ubuntu 22.04 + socat + C binary | Pwn challenges (port 1337) |
| `base:misc` | Alpine + Python 3.11 + socat | Misc challenges (port 4444) |
| `base:crypto` | Alpine + Python 3.11 | Crypto challenges |
| `base:forensics` | Alpine | Forensics challenges |
| `base:reversing` | Alpine | Reversing challenges |
| `base:osint` | Alpine | OSINT challenges |

All containers run as non-root (UID 1000), with `allowPrivilegeEscalation=false`, `capabilities: drop ALL`, and `seccomp: RuntimeDefault`.

---

## Deployment Process

The platform is fully automated via a single bootstrap script:

```bash
CTFD_URL=https://ctfd.infodays.net \
CTF_MASTER_SECRET=<secret> \
bash scripts/bootstrap.sh
```

This script runs 7 sequential phases:
1. Terraform provision (cluster, registry, DNS, ingress, cert-manager)
2. Build and push all 7 base challenge images to DOCR
3. Deploy K8s stack (MySQL, Redis, ProxySQL, CTFd, controller)
4. Configure CTFd via API (event settings, plugin install, admin account)
5. Import 50 teams × 4 players via CTFd API
6. Deploy all 36 challenges (create in CTFd + bulk-spawn K8s resources)
7. Import 1,750 per-team flags into CTFd

The script is idempotent — safe to re-run from any stage using `SKIP_TERRAFORM=1` and/or `SKIP_K8S_STACK=1` flags.

---

## Known Limitations & Notes

| Item | Detail |
|---|---|
| HTTP challenge isolation | No URL-based isolation (removed nginx auth_request as it broke curl/tool access). Isolation is via unique HMAC flags only. |
| TCP challenge isolation | NodePort bypasses nginx — same as HTTP. Cryptographic isolation only. |
| Node pool DNS | After node pool changes, `terraform apply -target=digitalocean_record.challenges_apex_a` must be run to update the apex A records |
| Static challenges | Only 1 static challenge currently deployed (Misc Welcome). More can be added by creating a manifest with `type: static` |
| Challenge content | All 36 challenge images use placeholder/example implementations. Actual challenge content must be built into each image before the event |
| Cert-manager DNS-01 | Uses external DNS resolvers (8.8.8.8, 1.1.1.1) because CoreDNS inside DOKS cannot validate ACME TXT records |

---

## Pending Before Event

- [ ] Replace placeholder challenge content with actual CTF puzzles in each base image
- [ ] Rebuild and push updated images to DOCR
- [ ] Final load test (400 VU / 100 teams × 4 players) to validate at full capacity
- [ ] Populate `data/teams.csv` with real participant names, emails, and passwords
- [ ] Re-run `import-teams.py` with actual team data
- [ ] Confirm `challenges.infodays.net` DNS is delegated and resolving correctly from participant networks
- [ ] Event day: run `terraform apply -target=digitalocean_record.challenges_apex_a` to ensure all current worker IPs are in DNS
