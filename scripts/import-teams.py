#!/usr/bin/env python3
"""
import-teams.py - Bulk create CTFd team accounts from CSV
Idempotent script that checks for existing teams before creating.
"""

import argparse
import csv
import sys
import requests


def validate_email(email):
    """Basic email validation."""
    return "@" in email and "." in email.split("@")[1]


def validate_row(row, row_num):
    """Validate a single CSV row. Returns (is_valid, error_message)."""
    errors = []

    if not row.get("team_name") or not row["team_name"].strip():
        errors.append("team_name is empty")

    if not row.get("email") or not row["email"].strip():
        errors.append("email is empty")
    elif not validate_email(row["email"]):
        errors.append("email format invalid")

    if not row.get("password") or not row["password"].strip():
        errors.append("password is empty")
    elif len(row["password"]) < 8:
        errors.append(f"password too short (need ≥8 chars, got {len(row['password'])})")

    if errors:
        return False, ", ".join(errors)
    return True, None


def main():
    parser = argparse.ArgumentParser(description="Bulk import CTFd teams from CSV")
    parser.add_argument("csv_file", help="CSV file path (columns: team_name, email, password)")
    parser.add_argument("--ctfd-url", required=True, help="CTFd base URL")
    parser.add_argument("--admin-token", required=True, help="CTFd admin API token")
    parser.add_argument("--dry-run", action="store_true", help="Validate CSV without making API calls")

    args = parser.parse_args()

    # Read and parse CSV — validate headers BEFORE exhausting the reader
    try:
        with open(args.csv_file, "r") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                print(f"ERROR: CSV has no headers or is empty: {args.csv_file}", file=sys.stderr)
                return 2
            required_cols = {"team_name", "email", "password"}
            headers = set(reader.fieldnames)
            if not required_cols.issubset(headers):
                print(f"ERROR: Missing required columns. Expected: {required_cols}, got: {headers}", file=sys.stderr)
                return 2
            rows = list(reader)
    except FileNotFoundError:
        print(f"ERROR: CSV file not found: {args.csv_file}", file=sys.stderr)
        return 2
    except csv.Error as e:
        print(f"ERROR: CSV parse error: {e}", file=sys.stderr)
        return 2

    if not rows:
        print("ERROR: CSV has headers but no data rows", file=sys.stderr)
        return 2

    # Pre-flight API connectivity and auth check (skip in dry-run)
    if not args.dry_run:
        try:
            probe = requests.get(
                f"{args.ctfd_url}/api/v1/teams",
                headers={"Authorization": f"Token {args.admin_token}"},
                timeout=10
            )
            if probe.status_code == 401:
                print("ERROR: CTFd authentication failed (401) — check admin token", file=sys.stderr)
                return 3
        except requests.RequestException as e:
            print(f"ERROR: CTFd API unreachable: {e}", file=sys.stderr)
            return 3

    print(f"Processing {args.csv_file} ({len(rows)} rows)...\n")

    created = 0
    skipped = 0
    failed = 0

    # Process each row
    for idx, row in enumerate(rows, 1):
        team_name = row["team_name"].strip()
        email = row["email"].strip()
        password = row["password"].strip()

        # Validate row
        is_valid, error_msg = validate_row(row, idx)
        if not is_valid:
            print(f"[{idx}/{len(rows)}] {team_name or '(unnamed)'} — failed ({error_msg})")
            failed += 1
            continue

        if args.dry_run:
            print(f"[{idx}/{len(rows)}] {team_name} — would create")
            created += 1
            continue

        # Check if team already exists
        try:
            check_resp = requests.get(
                f"{args.ctfd_url}/api/v1/teams",
                headers={"Authorization": f"Token {args.admin_token}"},
                timeout=10
            )
            if check_resp.status_code != 200:
                print(f"[{idx}/{len(rows)}] {team_name} — failed (API check failed: HTTP {check_resp.status_code})")
                failed += 1
                continue
            existing_teams = check_resp.json().get("data", [])
            if any(t.get("name") == team_name for t in existing_teams):
                print(f"[{idx}/{len(rows)}] {team_name} — skipped (already exists)")
                skipped += 1
                continue
        except requests.RequestException as e:
            print(f"[{idx}/{len(rows)}] {team_name} — failed (API error: {e})")
            failed += 1
            continue

        # Create user account
        try:
            user_resp = requests.post(
                f"{args.ctfd_url}/api/v1/users",
                headers={
                    "Authorization": f"Token {args.admin_token}",
                    "Content-Type": "application/json"
                },
                json={"name": team_name, "email": email, "password": password, "type": "user"},
                timeout=10
            )
            if user_resp.status_code not in (200, 201):
                error_detail = user_resp.json().get("errors", {})
                print(f"[{idx}/{len(rows)}] {team_name} — failed (user creation error: {error_detail})")
                failed += 1
                continue
            user_id = user_resp.json()["data"]["id"]
        except requests.RequestException as e:
            print(f"[{idx}/{len(rows)}] {team_name} — failed (API error: {e})")
            failed += 1
            continue

        # Create team
        try:
            team_resp = requests.post(
                f"{args.ctfd_url}/api/v1/teams",
                headers={
                    "Authorization": f"Token {args.admin_token}",
                    "Content-Type": "application/json"
                },
                json={"name": team_name, "email": email, "password": password},
                timeout=10
            )
            if team_resp.status_code not in (200, 201):
                error_detail = team_resp.json().get("errors", {})
                print(f"[{idx}/{len(rows)}] {team_name} — failed (team creation error: {error_detail})")
                failed += 1
                continue
            team_id = team_resp.json()["data"]["id"]
        except requests.RequestException as e:
            print(f"[{idx}/{len(rows)}] {team_name} — failed (API error: {e})")
            failed += 1
            continue

        # Add user to team as captain
        try:
            member_resp = requests.post(
                f"{args.ctfd_url}/api/v1/teams/{team_id}/members",
                headers={
                    "Authorization": f"Token {args.admin_token}",
                    "Content-Type": "application/json"
                },
                json={"user_id": user_id},
                timeout=10
            )
            # Set user as team captain
            requests.patch(
                f"{args.ctfd_url}/api/v1/teams/{team_id}",
                headers={
                    "Authorization": f"Token {args.admin_token}",
                    "Content-Type": "application/json"
                },
                json={"captain_id": user_id},
                timeout=10
            )
            print(f"[{idx}/{len(rows)}] {team_name} — created ✓")
            created += 1
        except requests.RequestException as e:
            print(f"[{idx}/{len(rows)}] {team_name} — failed (API error: {e})")
            failed += 1

    # Summary
    if args.dry_run:
        print(f"\n[DRY RUN] Summary: {created} would create, {failed} failed validation.")
        return 0

    print(f"\nSummary: {created} created, {skipped} skipped, {failed} failed.")

    if failed > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
