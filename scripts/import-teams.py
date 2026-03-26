#!/usr/bin/env python3
"""
import-teams.py — Bulk create CTFd teams from a CSV file.

Idempotent: existing teams and users are skipped, not duplicated.

Each CSV row creates:
  1. A user account  (the team captain)
  2. A team          (same name as the user)
  3. The user is added to the team as captain

CSV columns required: team_name, email, password

Credentials are read from environment variables (auto-set by setup-ctfd.sh)
or passed as CLI arguments. Environment takes priority over CLI args.

Usage (auto — called by setup-ctfd.sh):
  CTFD_URL=... CTFD_ADMIN_TOKEN=... python3 scripts/import-teams.py data/teams.csv

Usage (manual):
  python3 scripts/import-teams.py data/teams.csv \\
    --ctfd-url https://ctfd.infodays.net \\
    --admin-token ctfd_xxxxx

Usage (dry run — validate CSV only, no API calls):
  python3 scripts/import-teams.py data/teams.csv --dry-run
"""

import argparse
import csv
import os
import sys

import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_row(row, idx):
    errors = []
    if not row.get("team_name", "").strip():
        errors.append("team_name is empty")
    email = row.get("email", "").strip()
    if not email:
        errors.append("email is empty")
    elif "@" not in email or "." not in email.split("@")[-1]:
        errors.append("email format invalid")
    pwd = row.get("password", "").strip()
    if not pwd:
        errors.append("password is empty")
    elif len(pwd) < 8:
        errors.append(f"password too short ({len(pwd)} chars, need ≥8)")
    return errors


def api(session, method, url, **kwargs):
    """Thin wrapper: always includes Content-Type (CTFd requires it even on GETs)."""
    resp = session.request(method, url, timeout=15, **kwargs)
    return resp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bulk import CTFd teams from CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv_file", help="CSV file (columns: team_name, email, password)")
    parser.add_argument("--ctfd-url",    default=os.environ.get("CTFD_URL", ""),
                        help="CTFd base URL (default: $CTFD_URL)")
    parser.add_argument("--admin-token", default=os.environ.get("CTFD_ADMIN_TOKEN", ""),
                        help="CTFd admin API token (default: $CTFD_ADMIN_TOKEN)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate CSV without making any API calls")
    args = parser.parse_args()

    if not args.dry_run:
        if not args.ctfd_url:
            print("ERROR: CTFd URL not set. Pass --ctfd-url or set CTFD_URL.", file=sys.stderr)
            return 2
        if not args.admin_token:
            print("ERROR: Admin token not set. Pass --admin-token or set CTFD_ADMIN_TOKEN.", file=sys.stderr)
            return 2

    # -----------------------------------------------------------------------
    # Read + validate CSV
    # -----------------------------------------------------------------------
    try:
        with open(args.csv_file) as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                print(f"ERROR: CSV is empty: {args.csv_file}", file=sys.stderr)
                return 2
            missing = {"team_name", "email", "password"} - set(reader.fieldnames)
            if missing:
                print(f"ERROR: CSV missing columns: {missing}", file=sys.stderr)
                return 2
            rows = list(reader)
    except FileNotFoundError:
        print(f"ERROR: File not found: {args.csv_file}", file=sys.stderr)
        return 2

    if not rows:
        print("ERROR: CSV has no data rows.", file=sys.stderr)
        return 2

    print(f"Processing {args.csv_file} ({len(rows)} rows)...\n")

    # Dry run: just validate rows
    if args.dry_run:
        invalid = 0
        for idx, row in enumerate(rows, 1):
            errors = validate_row(row, idx)
            name = row.get("team_name", "(unnamed)").strip()
            if errors:
                print(f"[{idx}/{len(rows)}] {name} — INVALID: {', '.join(errors)}")
                invalid += 1
            else:
                print(f"[{idx}/{len(rows)}] {name} — OK")
        print(f"\n[DRY RUN] {len(rows) - invalid} valid, {invalid} invalid.")
        return 0 if invalid == 0 else 1

    # -----------------------------------------------------------------------
    # Set up session with auth headers
    # -----------------------------------------------------------------------
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {args.admin_token}",
        "Content-Type": "application/json",
    })
    base = args.ctfd_url.rstrip("/")

    # -----------------------------------------------------------------------
    # Preflight: verify connectivity and token
    # -----------------------------------------------------------------------
    try:
        probe = api(session, "GET", f"{base}/api/v1/users/me")
        if probe.status_code == 401:
            print("ERROR: Admin token is invalid (401).", file=sys.stderr)
            return 3
        if probe.status_code != 200:
            print(f"ERROR: CTFd API returned HTTP {probe.status_code}.", file=sys.stderr)
            return 3
    except requests.RequestException as e:
        print(f"ERROR: CTFd unreachable: {e}", file=sys.stderr)
        return 3

    # -----------------------------------------------------------------------
    # Fetch existing teams and users ONCE (not per-row)
    # -----------------------------------------------------------------------
    try:
        existing_teams = {
            t["name"]
            for page in range(1, 100)
            for t in api(session, "GET", f"{base}/api/v1/teams?page={page}").json().get("data", [])
        } if True else set()

        # More efficient: fetch page by page until empty
        existing_teams = set()
        page = 1
        while True:
            resp = api(session, "GET", f"{base}/api/v1/teams?page={page}").json()
            batch = resp.get("data", [])
            if not batch:
                break
            existing_teams.update(t["name"] for t in batch)
            if not resp.get("meta", {}).get("pagination", {}).get("next"):
                break
            page += 1

        existing_users = set()
        page = 1
        while True:
            resp = api(session, "GET", f"{base}/api/v1/users?page={page}").json()
            batch = resp.get("data", [])
            if not batch:
                break
            existing_users.update(u["name"] for u in batch)
            if not resp.get("meta", {}).get("pagination", {}).get("next"):
                break
            page += 1

    except requests.RequestException as e:
        print(f"ERROR: Failed to fetch existing data: {e}", file=sys.stderr)
        return 3

    print(f"Found {len(existing_teams)} existing teams, {len(existing_users)} existing users.\n")

    # -----------------------------------------------------------------------
    # Import rows
    # -----------------------------------------------------------------------
    created = skipped = failed = 0

    for idx, row in enumerate(rows, 1):
        name  = row["team_name"].strip()
        email = row["email"].strip()
        pwd   = row["password"].strip()
        label = f"[{idx}/{len(rows)}] {name}"

        errors = validate_row(row, idx)
        if errors:
            print(f"{label} — INVALID: {', '.join(errors)}")
            failed += 1
            continue

        if name in existing_teams:
            print(f"{label} — skipped (team already exists)")
            skipped += 1
            continue

        # 1. Create user (captain account)
        if name not in existing_users:
            try:
                r = api(session, "POST", f"{base}/api/v1/users", json={
                    "name": name, "email": email,
                    "password": pwd, "type": "user",
                })
                if r.status_code not in (200, 201):
                    errs = r.json().get("errors", r.text)
                    print(f"{label} — FAILED (user creation: {errs})")
                    failed += 1
                    continue
                user_id = r.json()["data"]["id"]
                existing_users.add(name)
            except requests.RequestException as e:
                print(f"{label} — FAILED (user creation: {e})")
                failed += 1
                continue
        else:
            # User exists, look up their ID
            try:
                r = api(session, "GET", f"{base}/api/v1/users?name={requests.utils.quote(name)}")
                matches = [u for u in r.json().get("data", []) if u["name"] == name]
                if not matches:
                    print(f"{label} — FAILED (user exists but ID not found)")
                    failed += 1
                    continue
                user_id = matches[0]["id"]
            except requests.RequestException as e:
                print(f"{label} — FAILED (user lookup: {e})")
                failed += 1
                continue

        # 2. Create team
        try:
            r = api(session, "POST", f"{base}/api/v1/teams", json={
                "name": name, "email": email, "password": pwd,
            })
            if r.status_code not in (200, 201):
                errs = r.json().get("errors", r.text)
                print(f"{label} — FAILED (team creation: {errs})")
                failed += 1
                continue
            team_id = r.json()["data"]["id"]
            existing_teams.add(name)
        except requests.RequestException as e:
            print(f"{label} — FAILED (team creation: {e})")
            failed += 1
            continue

        # 3. Add user to team + set as captain
        try:
            api(session, "POST", f"{base}/api/v1/teams/{team_id}/members",
                json={"user_id": user_id})
            api(session, "PATCH", f"{base}/api/v1/teams/{team_id}",
                json={"captain_id": user_id})
        except requests.RequestException as e:
            print(f"{label} — FAILED (team membership: {e})")
            failed += 1
            continue

        print(f"{label} — created")
        created += 1

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\nSummary: {created} created, {skipped} skipped, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
