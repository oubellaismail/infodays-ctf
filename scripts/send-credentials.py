#!/usr/bin/env python3
"""
send-credentials.py — Send CTFd login credentials to every player via SendGrid.

Reads data/teams.csv (columns: team_name, player_name, email, password) and
sends one personalised email per player with their username, password, team,
login URL, event start time, and rules link.

Prerequisites:
  pip install sendgrid

  SendGrid domain verification for infodays.net must be complete before sending.
  See docs/sendgrid-setup.md or the DNS section in infra/terraform/dns.tf.

Usage:
  # Dry run — preview all emails, no API calls
  python3 scripts/send-credentials.py data/teams.csv --dry-run

  # Send to one specific team only (test before full send)
  python3 scripts/send-credentials.py data/teams.csv --only-team "Alpha Squad"

  # Send to all players
  SENDGRID_API_KEY=SG.xxxx python3 scripts/send-credentials.py data/teams.csv

  # Full options
  python3 scripts/send-credentials.py data/teams.csv \\
    --sendgrid-key "$SENDGRID_API_KEY" \\
    --from-email "noreply@infodays.net" \\
    --from-name "InfoDays CTF" \\
    --event-date "2026-04-20 09:00 UTC" \\
    --ctfd-url "https://ctfd.infodays.net" \\
    --dry-run

Environment variables (override CLI args if set):
  SENDGRID_API_KEY   — SendGrid API key (required unless --dry-run)
  EVENT_DATE         — Human-readable event start time
  CTFD_URL           — CTFd base URL (default: https://ctfd.infodays.net)
  FROM_EMAIL         — Sender address (default: noreply@infodays.net)

Exit codes:
  0 — all emails sent (or dry run completed)
  1 — CSV validation failed (nothing sent)
  2 — partial failure (some emails failed; see output)
  3 — all emails failed
"""

import argparse
import csv
import os
import sys
import time

REQUIRED_COLUMNS = {"team_name", "player_name", "email", "password"}

# ── Email templates ────────────────────────────────────────────────────────────

DISCORD_URL = "https://discord.gg/hdnm9SyQ"


def build_plain(player_name: str, team_name: str, password: str,
                ctfd_url: str, event_date: str) -> str:
    return f"""\
Hello {player_name},

You are registered for the InfoDays CTF Qualification as a member of team "{team_name}".

The qualification starts today at 8:00 PM.

Your login credentials:
  Username : {player_name}
  Password : {password}
  Platform : {ctfd_url}

Join our Discord server to stay updated: {DISCORD_URL}

Good luck,
InfoDays CTF Team
"""


def build_html(player_name: str, team_name: str, password: str,
               ctfd_url: str, event_date: str) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>InfoDays CTF — Login Credentials</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#222;background:#fff;">
  <div style="max-width:540px;margin:32px auto;padding:0 16px;">

    <p>Hello {player_name},</p>

    <p>You are registered for the <strong>InfoDays CTF Qualification</strong> as a member of team <strong>{team_name}</strong>.</p>

    <p>The qualification starts <strong>today at 8:00 PM</strong>.</p>

    <p>
      Username: <strong>{player_name}</strong><br>
      Password: <strong>{password}</strong><br>
      Platform: <a href="{ctfd_url}">{ctfd_url}</a>
    </p>

    <p>Join our Discord server to stay updated: <a href="{DISCORD_URL}">{DISCORD_URL}</a></p>

    <p>Good luck,<br>InfoDays CTF Team</p>

  </div>
</body>
</html>
"""


# ── CSV loading ────────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    """Load and validate the teams CSV. Raises SystemExit on error."""
    if not os.path.isfile(path):
        print(f"ERROR: CSV file not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("ERROR: CSV file is empty.", file=sys.stderr)
            sys.exit(1)

        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"ERROR: CSV missing columns: {', '.join(sorted(missing))}", file=sys.stderr)
            print(f"  Expected: {', '.join(sorted(REQUIRED_COLUMNS))}", file=sys.stderr)
            sys.exit(1)

        rows = list(reader)

    if not rows:
        print("ERROR: CSV has no data rows.", file=sys.stderr)
        sys.exit(1)

    # Validate each row
    errors = []
    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        for col in REQUIRED_COLUMNS:
            if not row.get(col, "").strip():
                errors.append(f"  Row {i}: '{col}' is empty")
        email = row.get("email", "").strip()
        if email and ("@" not in email or "." not in email.split("@")[-1]):
            errors.append(f"  Row {i}: email '{email}' looks invalid")

    if errors:
        print(f"ERROR: {len(errors)} validation error(s) in CSV:", file=sys.stderr)
        for e in errors[:20]:
            print(e, file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more", file=sys.stderr)
        sys.exit(1)

    return rows


# ── Sending ────────────────────────────────────────────────────────────────────

def send_email(sg_client, from_email: str, from_name: str,
               to_email: str, to_name: str,
               subject: str, plain: str, html: str) -> tuple[bool, str]:
    """
    Send one email via SendGrid. Returns (success, error_message).
    """
    from sendgrid.helpers.mail import Mail, Email, To, Content

    message = Mail()
    message.from_email = Email(from_email, from_name)
    message.to = [To(to_email, to_name)]
    message.subject = subject
    message.content = [
        Content("text/plain", plain),
        Content("text/html", html),
    ]

    try:
        response = sg_client.send(message)
        if response.status_code in (200, 201, 202):
            return True, ""
        return False, f"HTTP {response.status_code}: {response.body}"
    except Exception as e:
        return False, str(e)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send CTFd login credentials to all players via SendGrid."
    )
    parser.add_argument("csv_file", help="Path to teams CSV (team_name,player_name,email,password)")
    parser.add_argument("--sendgrid-key", default=os.environ.get("SENDGRID_API_KEY", ""),
                        help="SendGrid API key (or set SENDGRID_API_KEY env var)")
    parser.add_argument("--from-email", default=os.environ.get("FROM_EMAIL", "noreply@infodays.net"),
                        help="Sender email address (default: noreply@infodays.net)")
    parser.add_argument("--from-name", default="InfoDays CTF",
                        help="Sender display name (default: InfoDays CTF)")
    parser.add_argument("--event-date", default=os.environ.get("EVENT_DATE", "TBD"),
                        help="Event start date/time string shown in email")
    parser.add_argument("--ctfd-url", default=os.environ.get("CTFD_URL", "https://ctfd.infodays.net"),
                        help="CTFd base URL (default: https://ctfd.infodays.net)")
    parser.add_argument("--only-team", default="",
                        help="Send only to this team name (for targeted resends)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print emails to stdout without sending anything")
    parser.add_argument("--rate-limit", type=float, default=0.2,
                        help="Seconds between sends (default: 0.2 = 5/sec)")
    args = parser.parse_args()

    # Validate SendGrid key presence (unless dry run)
    if not args.dry_run and not args.sendgrid_key:
        print("ERROR: SendGrid API key required. Set SENDGRID_API_KEY or use --sendgrid-key.", file=sys.stderr)
        print("       Use --dry-run to preview emails without sending.", file=sys.stderr)
        sys.exit(1)

    # Load CSV
    rows = load_csv(args.csv_file)

    # Filter by team if requested
    if args.only_team:
        rows = [r for r in rows if r["team_name"].strip() == args.only_team]
        if not rows:
            print(f"ERROR: No players found for team '{args.only_team}'", file=sys.stderr)
            sys.exit(1)
        print(f"Targeting team '{args.only_team}': {len(rows)} player(s)")

    total = len(rows)
    subject = "InfoDays CTF — Your Login Credentials"

    if args.dry_run:
        print(f"DRY RUN — {total} email(s) would be sent\n")
        print("=" * 60)
        for row in rows:
            player = row["player_name"].strip()
            team   = row["team_name"].strip()
            email  = row["email"].strip()
            pwd    = row["password"].strip()
            plain  = build_plain(player, team, pwd, args.ctfd_url, args.event_date)
            print(f"TO: {email} ({player}, team: {team})")
            print(f"SUBJECT: {subject}")
            print(plain)
            print("-" * 60)
        print(f"\nDRY RUN complete — {total} email(s) previewed, nothing sent.")
        sys.exit(0)

    # Import sendgrid here so missing package gives a clear error
    try:
        import sendgrid as sg_module
    except ImportError:
        print("ERROR: 'sendgrid' package not installed.", file=sys.stderr)
        print("  Run: pip install sendgrid", file=sys.stderr)
        sys.exit(1)

    sg = sg_module.SendGridAPIClient(api_key=args.sendgrid_key)

    print(f"Sending credentials to {total} player(s) from {args.from_email}...")
    print(f"  Event date : {args.event_date}")
    print(f"  CTFd URL   : {args.ctfd_url}")
    print()

    sent = 0
    failed = 0
    failures = []

    for i, row in enumerate(rows, start=1):
        player = row["player_name"].strip()
        team   = row["team_name"].strip()
        email  = row["email"].strip()
        pwd    = row["password"].strip()

        plain = build_plain(player, team, pwd, args.ctfd_url, args.event_date)
        html  = build_html(player, team, pwd, args.ctfd_url, args.event_date)

        ok, err = send_email(sg, args.from_email, args.from_name,
                             email, player, subject, plain, html)

        status = "✓" if ok else "✗"
        print(f"[{i:>4}/{total}] {status}  {email:<40}  ({team})")

        if ok:
            sent += 1
        else:
            failed += 1
            failures.append((email, player, team, err))
            print(f"          ERROR: {err}", file=sys.stderr)

        # Rate limit
        if i < total:
            time.sleep(args.rate_limit)

    # Summary
    print()
    print("━" * 50)
    print(f"Summary: {sent} sent, {failed} failed")

    if failures:
        print("\nFailed deliveries:")
        for email, player, team, err in failures:
            print(f"  {email} ({player}, {team}): {err}")
        print(f"\nTo resend failed team(s), use:")
        failed_teams = sorted({t for _, _, t, _ in failures})
        for t in failed_teams:
            print(f"  python3 {sys.argv[0]} {args.csv_file} --only-team \"{t}\"")

    if failed == total:
        sys.exit(3)
    elif failed > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
