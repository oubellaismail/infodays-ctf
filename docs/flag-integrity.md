# Flag Integrity — Team-Bound Flags

**Implemented**: 2026-04-03 | **Affects**: `ctfd-plugin/__init__.py`, `controller/import_flags.py`

---

## Problem

CTFd's built-in flag types (`static`, `regex`) have no team identity binding. A challenge has one
or more flag rows, and CTFd accepts a submission as correct if it matches **any** of them —
regardless of which team is submitting.

With 50 teams and 3 service challenges:
- Old setup: 150 static flag rows in the `flags` table (50 per challenge)
- Any team could submit another team's flag and score points
- No detection, no logging — the submission would simply succeed

## Solution

A custom `team` flag type implemented in `ctfd-plugin/__init__.py`. The expected flag is **derived
at validation time** from the submitting team's live session identity — it is never stored as a
plain string in the database.

### Flag derivation

```
flag = "infodays{" + HMAC-SHA256(CTF_MASTER_SECRET, "{team_id}:{challenge_manifest_id}")[:32] + "}"
```

- `CTF_MASTER_SECRET` — environment variable injected into the CTFd pod via K8s Secret
- `team_id` — numeric CTFd team ID from the active session (not from user input)
- `challenge_manifest_id` — e.g. `web-sqli`, `pwn-bof`, `misc-riddle` (stored in the flag row's `data` field)

Cross-team submission is cryptographically impossible without knowing `CTF_MASTER_SECRET`.

### Database schema

One row per service challenge in the `flags` table:

| Field        | Value              | Notes                                        |
|--------------|--------------------|----------------------------------------------|
| `type`       | `team`             | Activates the custom compare() method        |
| `content`    | `team-derived`     | Placeholder — not used for validation        |
| `data`       | `web-sqli`         | Challenge manifest ID — used for derivation  |

```sql
-- Example: 3 service challenges, 3 rows total (not 50×3=150)
SELECT id, challenge_id, type, content, data FROM flags;
-- 1 | 1 | team | team-derived | web-sqli
-- 2 | 2 | team | team-derived | pwn-bof
-- 3 | 3 | team | team-derived | misc-riddle
```

### Importing flags

`controller/import_flags.py` creates one `team` flag row per service challenge:

```bash
CTF_MASTER_SECRET=<secret> python3 controller/import_flags.py \
  --ctfd-url https://ctfd.infodays.net
```

The script is idempotent — skips challenges that already have a `team-derived` flag row.

---

## Cheating Detection

When a wrong flag is submitted, the plugin checks whether it belongs to any other team:

1. Fetch all other teams from the database (O(n), n≤50 — fast)
2. Derive each team's expected flag and compare using `hmac.compare_digest` (timing-safe)
3. If a match is found: insert a row into the `cheaters` table and return False
4. If no match: return False silently (just a wrong guess)

**Cheating detection never crashes flag validation** — all detection code is wrapped in
`try/except`. A detection failure does not affect the correctness of the False return.

### Cheaters table schema

```sql
CREATE TABLE IF NOT EXISTS cheaters (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    submitting_team_id    INT          NOT NULL,
    submitted_flag        TEXT         NOT NULL,
    owner_team_id         INT          NOT NULL,
    challenge_manifest_id VARCHAR(255) NOT NULL,
    submitted_at          DATETIME     NOT NULL,
    INDEX idx_submitting (submitting_team_id),
    INDEX idx_owner      (owner_team_id)
);
```

The table is created automatically at CTFd plugin load time (idempotent `CREATE TABLE IF NOT EXISTS`).

### Viewing the cheaters log

Admin-only endpoint (requires CTFd admin session):

```bash
curl -s https://ctfd.infodays.net/admin/cheaters \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" | jq .
```

Response fields:

| Field                 | Description                                       |
|-----------------------|---------------------------------------------------|
| `submitting_team`     | Name of the team that submitted the flag          |
| `submitting_team_id`  | Numeric ID of the submitting team                 |
| `submitted_flag`      | The exact flag string they submitted              |
| `owner_team`          | Name of the team whose flag was submitted         |
| `owner_team_id`       | Numeric ID of the flag's rightful owner           |
| `challenge`           | Challenge manifest ID (e.g. `web-sqli`)           |
| `submitted_at`        | UTC timestamp of the submission                   |

Results are ordered by `submitted_at DESC` (most recent first).

---

## Verifying flag integrity before the event

```bash
# 1. Confirm flag rows are type=team (not static)
curl -s -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://ctfd.infodays.net/api/v1/flags | jq '[.data[] | select(.type=="team")] | length'
# Expected: 3 (one per service challenge)

# 2. Verify correct flag accepted for your team
# Get your team's flag for web-sqli:
kubectl exec -n challenges deployment/team-1-web-sqli -- printenv FLAG
# Submit it via CTFd → should return "Correct"

# 3. Verify cross-team flag rejected
# Take team-2's flag (from their pod), submit it logged in as team-1
# Expected: "Incorrect" + entry appears in /admin/cheaters
```

---

## Operational Notes

- `CTF_MASTER_SECRET` must be set identically in:
  - The CTFd pod (env var from K8s secret `ctfd-secrets`)
  - The controller pod (same secret, used for bulk_spawn FLAG injection)
- If `CTF_MASTER_SECRET` is not set or empty, all `team` flag submissions return False
- If the challenge manifest ID in the flag row's `data` field doesn't match the pod's `CHALLENGE_ID`
  env var, flags won't match — verify with `printenv FLAG` inside the pod
