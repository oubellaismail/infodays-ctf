#!/usr/bin/env python3
"""
convert-registration-csv.py — Convert Google Form registration CSV to teams CSV.

Reads the InfoDays CTF Google Form export and produces data/teams.csv with columns:
    team_name, player_name, email, password, affiliation

One row per player. Passwords are auto-generated (16 chars, alphanumeric + symbols).
School column becomes team affiliation (applied to all members of the team).

Usage:
    python3 scripts/convert-registration-csv.py \
        "INFODAYS CTF REGISTRATION (réponses) - Réponses au formulaire 1.csv" \
        --out data/teams.csv
"""

import argparse
import csv
import os
import re
import secrets
import string
import sys
import unicodedata

PASS_CHARS = string.ascii_letters + string.digits + "!@#$%^&*"
PASS_LEN   = 16


def gen_password():
    return "".join(secrets.choice(PASS_CHARS) for _ in range(PASS_LEN))


def normalize_school(school: str) -> str:
    """Normalize school name (strip; fix missing spaces like ENSAAGADIR → ENSA Agadir)."""
    s = school.strip()
    # Fix variants without space: ENSAAGADIR, ENSAagadir, etc.
    import re
    s = re.sub(r'(?i)^ENSA\s*AGADIR$', 'ENSA Agadir', s)
    return s


def parse_members(row: dict) -> list[dict]:
    """Extract all non-empty members from a registration row."""
    members = []

    # Team leader
    discord   = row.get("Team leader's discord user", "").strip()
    full_name = row.get("Team leader's full name", "").strip()
    email     = row.get("Team leader's email", "").strip()
    name      = discord or full_name
    if name and email:
        members.append({"name": name, "email": email})

    # Members 1–3
    for i in range(1, 4):
        discord   = row.get(f"Member {i}'s discord user", "").strip()
        full_name = row.get(f"Member {i}'s full name", "").strip()
        email     = row.get(f"Member {i}'s email", "").strip()
        name      = discord or full_name
        if name and email:
            members.append({"name": name, "email": email})

    return members


def main():
    parser = argparse.ArgumentParser(description="Convert registration CSV to teams CSV")
    parser.add_argument("input_csv", help="Google Form export CSV")
    parser.add_argument("--out", default="data/teams.csv", help="Output path (default: data/teams.csv)")
    args = parser.parse_args()

    if not os.path.exists(args.input_csv):
        print(f"ERROR: File not found: {args.input_csv}", file=sys.stderr)
        return 1

    rows_out = []
    skipped  = []

    with open(args.input_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, 1):
            team_name   = row.get("Team Name", "").strip()
            school      = normalize_school(row.get("School", ""))
            members     = parse_members(row)

            if not team_name:
                skipped.append(f"Row {idx}: missing team name")
                continue
            if not members:
                skipped.append(f"Row {idx} ({team_name}): no valid members")
                continue

            for m in members:
                rows_out.append({
                    "team_name":   team_name,
                    "player_name": m["name"],
                    "email":       m["email"],
                    "password":    gen_password(),
                    "affiliation": school,
                })

    if not rows_out:
        print("ERROR: No valid rows produced.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["team_name", "player_name", "email", "password", "affiliation"])
        writer.writeheader()
        writer.writerows(rows_out)

    teams = len({r["team_name"] for r in rows_out})
    print(f"Converted: {teams} teams, {len(rows_out)} players → {args.out}")
    if skipped:
        print("Skipped:")
        for s in skipped:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
