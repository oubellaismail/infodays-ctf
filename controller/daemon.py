#!/usr/bin/env python3
"""
daemon.py - Lifetime daemon that enforces 60-minute pod timeout.

Polls all managed Deployments every 5 minutes.
Scales expired ones (>60 min since ctf/activated-at) to replicas=0.
"""

import os
import sys
import logging
import time
import argparse
from datetime import datetime, timezone
from typing import Any

from k8s_client import init_k8s_client

logger = logging.getLogger(__name__)


def reconcile_once(apps_v1: Any) -> int:
    """
    Reconcile once: suspend any pods that exceed 60-minute lifetime.

    Returns:
        Count of pods suspended this pass
    """
    suspended_count = 0

    # List all managed deployments
    deploys = apps_v1.list_namespaced_deployment(
        "challenges", label_selector="managed-by=ctf-controller"
    ).items

    now = datetime.now(timezone.utc)

    for deploy in deploys:
        # Skip if not active
        if deploy.spec.replicas != 1:
            continue

        # Skip if not activated
        activated_at_str = deploy.metadata.annotations.get("ctf/activated-at", "")
        if not activated_at_str:
            continue

        # Parse activation timestamp
        try:
            activated_at = datetime.fromisoformat(activated_at_str)
        except ValueError:
            logger.warning(f"Invalid activation timestamp for {deploy.metadata.name}: {activated_at_str}")
            continue

        # Check if expired (> 60 minutes = 3600 seconds)
        elapsed = now - activated_at
        if elapsed.total_seconds() > 3600:
            # Set annotation to None so K8s strategic merge patch deletes the key
            patch_body = {
                "metadata": {"annotations": {"ctf/activated-at": None}},
                "spec": {"replicas": 0},
            }
            try:
                apps_v1.patch_namespaced_deployment(deploy.metadata.name, "challenges", patch_body)
                logger.info(
                    f"Auto-suspended {deploy.metadata.name} (lifetime exceeded: {elapsed.total_seconds():.0f}s)"
                )
                suspended_count += 1
            except Exception as e:
                logger.error(f"Failed to suspend {deploy.metadata.name}: {e}")

    return suspended_count


def main():
    """Main entry point for daemon."""
    parser = argparse.ArgumentParser(description="Challenge lifetime daemon")
    parser.add_argument("--once", action="store_true", help="Run one iteration then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Validate environment
    if not os.getenv("CTF_MASTER_SECRET"):
        raise ValueError("CTF_MASTER_SECRET env var not set")

    # Initialize K8s client
    apps_v1, _, _ = init_k8s_client()

    logger.info("Challenge lifetime daemon started")

    if args.once:
        # Run once for testing
        suspended = reconcile_once(apps_v1)
        logger.info(f"Reconciliation complete: suspended {suspended} pod(s)")
        sys.exit(0)

    # Main loop: reconcile every 5 minutes
    while True:
        try:
            suspended = reconcile_once(apps_v1)
            if suspended > 0:
                logger.info(f"Suspended {suspended} pod(s) this pass")
        except Exception as e:
            logger.error(f"Reconciliation error: {e}", exc_info=False)

        # Sleep for 5 minutes
        time.sleep(300)


if __name__ == "__main__":
    main()
