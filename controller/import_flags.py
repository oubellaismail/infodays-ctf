#!/usr/bin/env python3
"""
import_flags.py - Import derived flags for all team × challenge pairs into CTFd.

Idempotent: safe to re-run. Skips flags that already exist.
"""

import os
import sys
import json
import argparse
import logging
from typing import Any

import httpx

from flag import derive_flag
from manifest_loader import load_manifests, load_flag_entries

logger = logging.getLogger(__name__)


def fetch_teams(ctfd_url: str, admin_token: str) -> list[dict]:
    """
    Fetch all teams from CTFd admin API.

    Args:
        ctfd_url: Base URL of CTFd instance
        admin_token: CTFd admin API token

    Returns:
        List of {id: str, name: str} dicts
    """
    url = f"{ctfd_url}/api/v1/teams?per_page=100"
    headers = {"Authorization": f"Token {admin_token}", "Content-Type": "application/json"}

    try:
        response = httpx.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        teams = data.get("data", [])
        logger.info(f"Fetched {len(teams)} teams from CTFd")
        return [{"id": str(t["id"]), "name": t.get("name", "")} for t in teams]
    except Exception as e:
        logger.error(f"Failed to fetch teams: {e}")
        raise


def fetch_challenges(ctfd_url: str, admin_token: str) -> dict:
    """
    Fetch all challenges and build a mapping of name → ctfd_id.

    Args:
        ctfd_url: Base URL of CTFd instance
        admin_token: CTFd admin API token

    Returns:
        Dict mapping challenge name → ctfd_id
    """
    url = f"{ctfd_url}/api/v1/challenges?per_page=100"
    headers = {"Authorization": f"Token {admin_token}", "Content-Type": "application/json"}

    try:
        response = httpx.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        challenges = data.get("data", [])

        # Build name → id mapping
        mapping = {}
        for ch in challenges:
            mapping[ch.get("name", "")] = ch["id"]

        logger.info(f"Fetched {len(challenges)} challenges from CTFd")
        return mapping
    except Exception as e:
        logger.error(f"Failed to fetch challenges: {e}")
        raise


def fetch_existing_flags(ctfd_url: str, admin_token: str, challenge_id: int) -> set[str]:
    """
    Fetch all flags for a specific challenge.

    Args:
        ctfd_url: Base URL of CTFd instance
        admin_token: CTFd admin API token
        challenge_id: CTFd challenge ID

    Returns:
        Set of flag strings already registered
    """
    url = f"{ctfd_url}/api/v1/flags?per_page=500&challenge_id={challenge_id}"
    headers = {"Authorization": f"Token {admin_token}", "Content-Type": "application/json"}

    try:
        response = httpx.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        flags = data.get("data", [])
        flag_set = {f.get("content", "") for f in flags}
        return flag_set
    except Exception as e:
        logger.error(f"Failed to fetch flags for challenge {challenge_id}: {e}")
        raise


def import_flag(ctfd_url: str, admin_token: str, challenge: dict, challenge_id_map: dict) -> str:
    """
    Import one team-bound flag entry per challenge into CTFd.

    Uses the custom 'team' flag type registered by the controller-plugin.
    CTFd validates on the fly: HMAC(CTF_MASTER_SECRET, "{team_id}:{manifest_id}")[:32]
    Cross-team flag submission is cryptographically rejected — one row covers all teams.

    Flag row:
        type    = "team"
        content = "team-derived"   (placeholder, not used for validation)
        data    = challenge manifest ID  e.g. "pwn-bof"

    Returns:
        "created" or "skipped"
    """
    challenge_name = challenge.get("name", "")
    challenge_manifest_id = challenge["id"]
    ctfd_challenge_id = challenge_id_map.get(challenge_name)

    if not ctfd_challenge_id:
        logger.warning(f"Challenge not found in CTFd: {challenge_name}")
        return "skipped"

    # Skip if a team flag already exists for this challenge
    existing_flags = fetch_existing_flags(ctfd_url, admin_token, ctfd_challenge_id)
    if "team-derived" in existing_flags:
        logger.info(f"Skipped (team flag exists): {challenge_name}")
        return "skipped"

    url = f"{ctfd_url}/api/v1/flags"
    headers = {"Authorization": f"Token {admin_token}", "Content-Type": "application/json"}
    body = {
        "challenge_id": ctfd_challenge_id,
        "type": "team",
        "content": "team-derived",
        "data": challenge_manifest_id,
    }

    try:
        response = httpx.post(url, headers=headers, json=body)
        response.raise_for_status()
        logger.info(f"Created team flag: {challenge_name} (manifest: {challenge_manifest_id})")
        return "created"
    except Exception as e:
        logger.error(f"Failed to import flag for challenge {challenge_name}: {e}")
        raise


def import_lab_flags(ctfd_url: str, admin_token: str, lab: dict, challenge_id_map: dict) -> tuple[int, int]:
    """
    Import one team-bound flag row per sub-flag for a lab challenge.

    Lab manifests produce ONE CTFd challenge with N flag rows. Each flag row
    stores a JSON blob in the 'data' field so the LabChallenge class can read
    both the sub-flag id (for HMAC) and the point value (for partial awards):

        type    = "team"
        content = "team-derived:{sub_id}"   (unique placeholder — lets import skip existing rows)
        data    = JSON: {"sub_id": "...", "points": N, "deployment_id": "..."}

    Returns (created_count, skipped_count).
    """
    lab_name = lab.get("name", "")
    lab_id = lab["id"]
    ctfd_challenge_id = challenge_id_map.get(lab_name)

    if not ctfd_challenge_id:
        logger.warning(f"Lab challenge not found in CTFd: {lab_name}")
        return (0, 0)

    # Fetch existing flag "content" strings so we can skip already-imported sub-flags
    existing = fetch_existing_flags(ctfd_url, admin_token, ctfd_challenge_id)

    url = f"{ctfd_url}/api/v1/flags"
    headers = {"Authorization": f"Token {admin_token}", "Content-Type": "application/json"}

    created = 0
    skipped = 0

    for sub in lab.get("flags", []):
        sub_id = sub.get("id")
        sub_points = int(sub.get("points", 0))
        if not sub_id:
            logger.error(f"Lab {lab_id}: sub-flag missing 'id' — skipped")
            continue

        marker = f"team-derived:{sub_id}"
        if marker in existing:
            logger.info(f"Skipped (exists): {lab_name} / {sub_id}")
            skipped += 1
            continue

        flag_data = json.dumps({
            "sub_id": sub_id,
            "points": sub_points,
            "deployment_id": lab_id,
        })
        body = {
            "challenge_id": ctfd_challenge_id,
            "type": "team",
            "content": marker,
            "data": flag_data,
        }
        response = httpx.post(url, headers=headers, json=body)
        response.raise_for_status()
        logger.info(f"Created lab flag: {lab_name} / {sub_id} ({sub_points} pts)")
        created += 1

    return (created, skipped)


def main(ctfd_url: str, admin_token: str) -> None:
    """Entry point for flag import workflow."""
    logger.info("Starting flag import (team-bound mode)...")

    # CTF_MASTER_SECRET must be set — used at validation time by CTFd, not here
    if not os.getenv("CTF_MASTER_SECRET"):
        raise ValueError("CTF_MASTER_SECRET env var not set")

    challenge_id_map = fetch_challenges(ctfd_url, admin_token)

    # Allowed categories for flag import (excludes internal-only)
    ALLOWED_CATEGORIES = {"web", "pwn", "misc", "crypto", "forensics", "reversing", "osint", "lab"}

    # Lab manifests are handled separately — one CTFd challenge, N flag rows.
    # Non-lab manifests use the existing single-flag / expanded-bundle path.
    labs = [m for m in load_manifests()
            if m.get("lab") is True
            and m.get("category", "").lower() in ALLOWED_CATEGORIES]
    non_lab_entries = [c for c in load_flag_entries()
                       if not (c.get("lab") is True)
                       and c.get("category", "").lower() in ALLOWED_CATEGORIES]

    logger.info(f"Loaded {len(labs)} lab manifests and {len(non_lab_entries)} regular flag entries")

    created = 0
    skipped = 0
    errors = 0

    # Regular single-flag / legacy-bundle entries
    for challenge in non_lab_entries:
        try:
            result = import_flag(ctfd_url, admin_token, challenge, challenge_id_map)
            if result == "created":
                created += 1
            elif result == "skipped":
                skipped += 1
        except Exception as e:
            logger.error(f"Error importing flag for {challenge['id']}: {e}")
            errors += 1

    # Lab manifests: N flag rows per CTFd challenge
    for lab in labs:
        try:
            c, s = import_lab_flags(ctfd_url, admin_token, lab, challenge_id_map)
            created += c
            skipped += s
        except Exception as e:
            logger.error(f"Error importing lab flags for {lab['id']}: {e}")
            errors += 1

    logger.info(f"Done: {created} created, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Import derived flags into CTFd")
    parser.add_argument("--ctfd-url", required=True, help="CTFd base URL")

    args = parser.parse_args()

    # Get admin token from environment
    admin_token = os.getenv("CTFD_ADMIN_TOKEN")
    if not admin_token:
        print("Error: CTFD_ADMIN_TOKEN environment variable not set")
        sys.exit(1)

    try:
        main(args.ctfd_url, admin_token)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
