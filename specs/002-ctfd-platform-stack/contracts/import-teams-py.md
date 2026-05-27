# Contract: import-teams.py

**Script**: `scripts/import-teams.py`
**Purpose**: Bulk-creates CTFd teams and individual player accounts from a CSV file. Idempotent — safe to re-run.

## Inputs

### Command-Line Arguments

```
python scripts/import-teams.py [OPTIONS] <csv_file>
```

| Argument | Required | Description |
|----------|----------|-------------|
| `csv_file` | Yes | Path to the CSV file containing team and player data |
| `--ctfd-url URL` | Yes | Base URL of the CTFd instance |
| `--admin-token TOKEN` | Yes | CTFd admin API token |
| `--dry-run` | No | Validate CSV and show what would be created without making API calls |

### CSV Format

File: `data/teams-template.csv`

```csv
team_name,player_name,email,password
Alpha Squad,Alice,alice@example.com,s3cur3pass1
Alpha Squad,Bob,bob@example.com,s3cur3pass2
Alpha Squad,Charlie,charlie@example.com,s3cur3pass3
Alpha Squad,Dave,dave@example.com,s3cur3pass4
Beta Force,Eve,eve@example.com,s3cur3pass5
Beta Force,Frank,frank@example.com,s3cur3pass6
```

**Column rules**:
- `team_name`: non-empty string; rows with the same team_name are grouped into one team
- `player_name`: non-empty string, unique across the file (used as CTFd username)
- `email`: valid email format, unique across the file
- `password`: non-empty string, minimum 8 characters

## Behaviour

1. Reads and validates the CSV file; exits with code 2 if the file cannot be parsed.
2. Groups rows by `team_name` (preserving order of first appearance).
3. Pre-flight check: verifies CTFd API is reachable and token is valid; exits with code 3 on failure.
4. Fetches all existing teams and users from CTFd (one-time, not per-row).
5. For each team group:
   a. If team already exists: looks up its ID for member assignment; records as `skipped`.
   b. If team does not exist: creates it via `POST /api/v1/teams` using the first member's email.
   c. For each player in the group:
      1. If user already exists: records as `skipped`.
      2. Creates a user account via `POST /api/v1/users` (name=player_name, email, password, type=user).
      3. Adds the user to the team via `POST /api/v1/teams/{id}/members`.
      4. If this is the first player for the team: sets them as captain via `PATCH /api/v1/teams/{id}`.
6. Malformed rows (missing columns, invalid email, password < 8 chars) are recorded as `failed` without stopping remaining rows.
7. Prints a summary after processing all rows.

> **Player mode**: CTFd `user_mode` is set to `"teams"`. Each team has multiple individual user accounts (typically 4 per team). All players on a team share the same `team_id`, which is the identity boundary for challenge instances, flags, and isolation. Players log in with their own credentials but see and interact with their team's shared challenge state.

## Outputs

### Stdout

```
Processing data/teams.csv (200 players across 50 teams)...

Found 0 existing teams, 1 existing users.

[Team] Alpha Squad — created (id=1)
  [1/4] Alpha Squad P1 — created
  [2/4] Alpha Squad P2 — created
  [3/4] Alpha Squad P3 — created
  [4/4] Alpha Squad P4 — created
[Team] Beta Force — skipped (already exists)
  [1/4] Beta Force P1 — skipped (user already exists)
  ...

Summary:
  Teams:   49 created, 1 skipped
  Players: 196 created, 4 skipped, 0 failed
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All rows processed; zero failures |
| 1 | One or more rows failed (partial success — summary printed) |
| 2 | CSV file could not be read or parsed (no teams processed) |
| 3 | CTFd API unreachable or authentication failed |

## Example Usage

```bash
# Dry run first
python3 scripts/import-teams.py --dry-run data/teams.csv

# Live import (credentials from env)
CTFD_URL=https://ctfd.infodays.net CTFD_ADMIN_TOKEN=ctfd_abc123 \
  python3 scripts/import-teams.py data/teams.csv

# Live import (credentials from CLI)
python3 scripts/import-teams.py --ctfd-url https://ctfd.infodays.net \
  --admin-token ctfd_abc123 data/teams.csv

# Re-run is safe — existing teams/users are skipped
python3 scripts/import-teams.py data/teams.csv
```

## teams-template.csv Structure

```csv
team_name,player_name,email,password
Team Name Here,Player One,player1@example.com,ChangeThisPassword1
Team Name Here,Player Two,player2@example.com,ChangeThisPassword2
Team Name Here,Player Three,player3@example.com,ChangeThisPassword3
Team Name Here,Player Four,player4@example.com,ChangeThisPassword4
```

Operators copy this file to `data/teams.csv`, fill in real team and player details, and run the import script. `data/teams.csv` MUST be gitignored (contains real credentials).

## Data Model

### Before (shared account mode)
```
1 CSV row → 1 user + 1 team (user = captain, 4 people share the login)
```

### After (player mode)
```
4 CSV rows (same team_name) → 4 users + 1 team (first user = captain)
```

### Why nothing else changes

The entire platform is keyed on `team_id`, not `user_id`:

| Component | Identity used | Impact |
|---|---|---|
| Flag derivation (`controller/flag.py`, plugin) | `team_id` | None |
| Bulk spawn (`controller/bulk_spawn.py`) | `team_id` | None |
| Controller API (`controller/api.py`) | `team_id` | None |
| K8s resource naming (`controller/naming.py`) | `team-{id}-{challenge}` | None |
| Challenge isolation (`/team-verify`) | `get_current_team().id` | None |
| Plugin JS (`plugin.js`) | `window.CTF_CONTROLLER.team_id` | None |
| Pod cap (4 active per team) | `team_id` label selector | None |
| Network policies | `team={id}` labels | None |

CTFd natively resolves `user → team` via `get_current_team()`. When any player on a team logs in, they get the same `team_id` in their session. All downstream systems see the same team identity regardless of which player triggered the action.

### Cheater detection

The `cheaters` table now tracks the individual player who submitted another team's flag:

```sql
CREATE TABLE cheaters (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    submitting_team_id    INT         NOT NULL,
    submitting_user_id    INT             NULL,   -- the individual cheater
    submitted_flag        TEXT        NOT NULL,
    owner_team_id         INT         NOT NULL,
    challenge_manifest_id VARCHAR(255) NOT NULL,
    submitted_at          DATETIME    NOT NULL,
    INDEX idx_submitting (submitting_team_id),
    INDEX idx_user       (submitting_user_id),
    INDEX idx_owner      (owner_team_id)
);
```

The `/admin/cheaters` API endpoint returns `submitting_user` and `submitting_user_id` alongside the team info, so admins can identify exactly which player shared or used a leaked flag.
