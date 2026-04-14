#!/usr/bin/env python3
"""
import_flags.py - Import derived flags for all team × challenge pairs into CTFd.

Idempotent: safe to re-run. Skips flags that already exist.
"""

import os
import sys
import argparse
import logging
from typing import Any

import httpx

from flag import derive_flag
from manifest_loader import load_manifests

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


def main(ctfd_url: str, admin_token: str) -> None:
    """Entry point for flag import workflow."""
    logger.info("Starting flag import (team-bound mode)...")

    # CTF_MASTER_SECRET must be set — used at validation time by CTFd, not here
    if not os.getenv("CTF_MASTER_SECRET"):
        raise ValueError("CTF_MASTER_SECRET env var not set")

    challenge_id_map = fetch_challenges(ctfd_url, admin_token)

    # All challenges (service + static) use the custom 'team' flag type with
    # HMAC-derived per-team flags. Static challenges serve per-team zips via
    # the plugin download endpoint; service challenges validate on submission.
    challenges = [c for c in load_manifests()
                  if c["category"] in {"web", "pwn", "misc", "crypto", "forensics", "reversing", "osint"}]
    logger.info(f"Loaded {len(challenges)} challenges (service + static)")

    # One team flag row per challenge — no team loop needed
    created = 0
    skipped = 0
    errors = 0

    for challenge in challenges:
        try:
            result = import_flag(ctfd_url, admin_token, challenge, challenge_id_map)
            if result == "created":
                created += 1
            elif result == "skipped":
                skipped += 1
        except Exception as e:
            logger.error(f"Error importing flag for {challenge['id']}: {e}")
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
