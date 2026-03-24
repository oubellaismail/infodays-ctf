# Contract: import-teams.py

**Script**: `scripts/import-teams.py`
**Purpose**: Bulk-creates CTFd team accounts from a CSV file. Idempotent — safe to re-run.

## Inputs

### Command-Line Arguments

```
python scripts/import-teams.py [OPTIONS] <csv_file>
```

| Argument | Required | Description |
|----------|----------|-------------|
| `csv_file` | Yes | Path to the CSV file containing team data |
| `--ctfd-url URL` | Yes | Base URL of the CTFd instance |
| `--admin-token TOKEN` | Yes | CTFd admin API token |
| `--dry-run` | No | Validate CSV and show what would be created without making API calls |

### CSV Format

File: `data/teams-template.csv`

```csv
team_name,email,password
Alpha Squad,alpha@example.com,s3cur3pass1
Beta Force,beta@example.com,s3cur3pass2
```

**Column rules**:
- `team_name`: non-empty string, unique across the file
- `email`: valid email format, unique across the file
- `password`: non-empty string, minimum 8 characters

## Behaviour

1. Reads and validates the CSV file; exits with code 2 if the file cannot be parsed.
2. Pre-flight check: verifies CTFd API is reachable and token is valid; exits with code 3 on failure.
3. For each row:
   a. Checks if a team with that `team_name` already exists via `GET /api/v1/teams`.
   b. If it exists: records as `skipped (already exists)`.
   c. If it does not exist:
      1. Creates a user account via `POST /api/v1/users` (name=team_name, email, password).
      2. Creates the team via `POST /api/v1/teams` (name=team_name, email, password).
      3. Adds the user to the team via `POST /api/v1/teams/{id}/members`.
      4. Sets the user as team captain via `PATCH /api/v1/teams/{id}`.
      5. Records as `created` or `failed`.
4. Malformed rows (missing columns, invalid email, password < 8 chars) are recorded as `failed` without stopping remaining rows.
5. Prints a summary after processing all rows.

> **Why user + team**: CTFd teams mode requires individual user accounts for login. Teams are containers that users belong to. The script creates one user per team (the captain) so teams can log in immediately after import using `team_name` as the username.

## Outputs

### Stdout

```
Processing teams-template.csv (3 rows)...
[1/3] Alpha Squad — created ✓
[2/3] Beta Force — skipped (already exists)
[3/3] Gamma Team — failed (API error 400: email already in use)

Summary: 1 created, 1 skipped, 1 failed.
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
python scripts/import-teams.py --ctfd-url https://ctfd.infodays.net \
  --admin-token ctfd_abc123 --dry-run data/teams.csv

# Live import
python scripts/import-teams.py --ctfd-url https://ctfd.infodays.net \
  --admin-token ctfd_abc123 data/teams.csv
```

## teams-template.csv Structure

```csv
team_name,email,password
Team Name Here,team@example.com,ChangeThisPassword1
```

Operators copy this file to `data/teams.csv`, fill in real team details, and run the import script. `data/teams.csv` MUST be gitignored (contains real credentials).
