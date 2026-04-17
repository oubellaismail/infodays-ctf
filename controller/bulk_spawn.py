#!/usr/bin/env python3
"""
bulk_spawn.py - Pre-spawn all challenge pods for all teams at replicas=0.

Idempotent: safe to re-run. Parallel execution via ThreadPoolExecutor.
"""

import os
import sys
import argparse
import logging
import base64
import json
import concurrent.futures
from typing import Any

import httpx
from kubernetes.client import ApiException
from kubernetes.client.models import (
    V1Secret,
    V1ObjectMeta,
    V1Deployment,
    V1DeploymentSpec,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ContainerPort,
    V1EnvVar,
    V1EnvVarSource,
    V1SecretKeySelector,
    V1ResourceRequirements,
    V1LabelSelector,
    V1Service,
    V1ServiceSpec,
    V1ServicePort,
    V1Ingress,
    V1IngressSpec,
    V1IngressRule,
    V1HTTPIngressRuleValue,
    V1HTTPIngressPath,
    V1IngressBackend,
    V1IngressServiceBackend,
    V1ServiceBackendPort,
    V1IngressTLS,
    V1SecurityContext,
    V1PodSecurityContext,
    V1Capabilities,
    V1SeccompProfile,
)

from k8s_client import init_k8s_client
from flag import derive_flag
from manifest_loader import load_manifests
from naming import deployment_name, secret_name, service_name, ingress_name, managed_labels


def _flag_env_vars(team_id: str, challenge: dict) -> tuple[dict, list]:
    """Build (secret_data, env_var_list) for a challenge's flags.

    Single-flag manifest: {FLAG: derive_flag(team_id, id)}, [EnvVar FLAG]
    Bundle manifest:      {FLAG1: ..., FLAG2: ...},          [EnvVar FLAG1, FLAG2, ...]
    """
    if "flags" in challenge:
        secret_data = {
            entry["env"]: derive_flag(team_id, entry["id"])
            for entry in challenge["flags"]
        }
        env_vars = [
            V1EnvVar(
                name=entry["env"],
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=secret_name(team_id, challenge["id"]),
                        key=entry["env"],
                    )
                ),
            )
            for entry in challenge["flags"]
        ]
    else:
        secret_data = {"FLAG": derive_flag(team_id, challenge["id"])}
        env_vars = [
            V1EnvVar(
                name="FLAG",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=secret_name(team_id, challenge["id"]),
                        key="FLAG",
                    )
                ),
            )
        ]
    return secret_data, env_vars

logger = logging.getLogger(__name__)


def fetch_teams(ctfd_url: str, admin_token: str) -> list[dict]:
    """
    Fetch all teams from CTFd admin API.

    Args:
        ctfd_url: Base URL of CTFd instance (e.g., "https://ctfd.infodays.net")
        admin_token: CTFd admin API token

    Returns:
        List of {id: str, name: str} dicts
    """
    url = f"{ctfd_url}/api/v1/teams?per_page=100"
    # Content-Type required on all CTFd token-auth requests (including GETs);
    # without it CTFd's token middleware skips auth and returns 302/500.
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


def create_secret(core_v1: Any, team_id: str, challenge: dict) -> str:
    """
    Create or skip a Kubernetes Secret containing the challenge flag.

    Args:
        core_v1: CoreV1Api instance
        team_id: Team identifier
        challenge: Challenge manifest dict with 'id' field

    Returns:
        "created" or "skipped"
    """
    challenge_id = challenge["id"]
    sec_name = secret_name(team_id, challenge_id)

    secret_data, _ = _flag_env_vars(team_id, challenge)
    body = V1Secret(
        metadata=V1ObjectMeta(
            name=sec_name,
            namespace="challenges",
            labels=managed_labels(team_id, challenge_id),
        ),
        string_data=secret_data,
    )

    try:
        core_v1.create_namespaced_secret("challenges", body)
        logger.info(f"Created secret: {sec_name}")
        return "created"
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Skipped (exists): {sec_name}")
            return "skipped"
        raise


def create_deployment(apps_v1: Any, team_id: str, challenge: dict) -> str:
    """
    Create or skip a Kubernetes Deployment for a challenge at replicas=0.

    Args:
        apps_v1: AppsV1Api instance
        team_id: Team identifier
        challenge: Challenge manifest dict

    Returns:
        "created" or "skipped"
    """
    challenge_id = challenge["id"]
    dep_name = deployment_name(team_id, challenge_id)
    labels = managed_labels(team_id, challenge_id)

    _, env_vars = _flag_env_vars(team_id, challenge)
    all_ports = [V1ContainerPort(container_port=challenge["port"])]
    for extra in challenge.get("extra_ports", []):
        all_ports.append(V1ContainerPort(container_port=extra["port"]))

    container = V1Container(
        name=challenge_id,
        image=challenge["image"],
        ports=all_ports,
        env=env_vars,
        resources=V1ResourceRequirements(
            limits={"cpu": "0.5", "memory": challenge.get("memory_limit", "128Mi")},
            requests={"cpu": "0.05", "memory": "32Mi"},
        ),
        security_context=V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=V1Capabilities(drop=["ALL"]),
            run_as_non_root=True,
            run_as_user=1000,
        ),
    )

    body = V1Deployment(
        metadata=V1ObjectMeta(
            name=dep_name,
            namespace="challenges",
            labels=labels,
            annotations={"ctf/activated-at": ""},
        ),
        spec=V1DeploymentSpec(
            replicas=0,
            selector=V1LabelSelector(match_labels=labels),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=labels),
                spec=V1PodSpec(
                    containers=[container],
                    security_context=V1PodSecurityContext(
                        run_as_non_root=True,
                        run_as_user=1000,
                        seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
                    ),
                ),
            ),
        ),
    )

    try:
        apps_v1.create_namespaced_deployment("challenges", body)
        logger.info(f"Created deployment: {dep_name}")
        return "created"
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Skipped (exists): {dep_name}")
            return "skipped"
        raise


def create_service(core_v1: Any, team_id: str, challenge: dict) -> str:
    """
    Create or skip a Kubernetes Service for a challenge.

    Args:
        core_v1: CoreV1Api instance
        team_id: Team identifier
        challenge: Challenge manifest dict

    Returns:
        "created" or "skipped"
    """
    challenge_id = challenge["id"]
    svc_name = service_name(team_id, challenge_id)
    labels = managed_labels(team_id, challenge_id)

    body = V1Service(
        metadata=V1ObjectMeta(
            name=svc_name,
            namespace="challenges",
            labels=labels,
        ),
        spec=V1ServiceSpec(
            type="NodePort" if challenge.get("type") in ("tcp", "http") else "ClusterIP",
            selector=labels,
            ports=[V1ServicePort(port=challenge["port"], target_port=challenge["port"])],
        ),
    )

    try:
        core_v1.create_namespaced_service("challenges", body)
        logger.info(f"Created service: {svc_name}")
        return "created"
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Skipped (exists): {svc_name}")
            return "skipped"
        raise


def create_http_ingress(net_v1: Any, team_id: str, challenge: dict) -> str:
    """
    Create or skip a Kubernetes Ingress for HTTP challenges.

    Args:
        net_v1: NetworkingV1Api instance
        team_id: Team identifier
        challenge: Challenge manifest dict

    Returns:
        "created" or "skipped"
    """
    challenge_id = challenge["id"]
    ing_name = ingress_name(team_id, challenge_id)
    host = f"team-{team_id}-{challenge_id}.challenges.infodays.net"
    svc_name = service_name(team_id, challenge_id)
    port = challenge["port"]

    body = V1Ingress(
        metadata=V1ObjectMeta(
            name=ing_name,
            namespace="challenges",
            annotations={
                "cert-manager.io/cluster-issuer": "letsencrypt-prod",
                "nginx.ingress.kubernetes.io/ssl-redirect": "true",
            },
        ),
        spec=V1IngressSpec(
            ingress_class_name="nginx",
            rules=[
                V1IngressRule(
                    host=host,
                    http=V1HTTPIngressRuleValue(
                        paths=[
                            V1HTTPIngressPath(
                                path="/",
                                path_type="Prefix",
                                backend=V1IngressBackend(
                                    service=V1IngressServiceBackend(
                                        name=svc_name,
                                        port=V1ServiceBackendPort(number=port),
                                    )
                                ),
                            )
                        ]
                    ),
                )
            ],
            tls=[
                V1IngressTLS(
                    hosts=[host],
                    secret_name=f"team-{team_id}-{challenge_id}-tls",
                )
            ],
        ),
    )

    try:
        net_v1.create_namespaced_ingress("challenges", body)
        logger.info(f"Created ingress: {ing_name}")
        return "created"
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Skipped (exists): {ing_name}")
            return "skipped"
        raise


def add_tcp_entry(core_v1: Any, team_id: str, challenge: dict) -> tuple[str, int]:
    """
    Add or skip TCP service entry in NGINX ConfigMap, assigning a port.

    Args:
        core_v1: CoreV1Api instance
        team_id: Team identifier
        challenge: Challenge manifest dict

    Returns:
        Tuple of ("created"|"skipped", port_number)
    """
    challenge_id = challenge["id"]
    svc_name = service_name(team_id, challenge_id)
    expected_val = f"challenges/{svc_name}:{challenge['port']}"

    # Read existing ConfigMap
    cm = core_v1.read_namespaced_config_map("tcp-services", "ingress-nginx")
    existing = cm.data or {}

    # Check if entry already exists
    for key, val in existing.items():
        if val == expected_val:
            logger.info(f"Skipped (exists): TCP port {key} for {svc_name}")
            return ("skipped", int(key))

    # Assign new port: max numeric key + 1, or start at 30000 if empty
    numeric_keys = [int(k) for k in existing.keys() if k.isdigit()]
    assigned_port = max(numeric_keys, default=29999) + 1

    # Patch ConfigMap with new entry
    patch_body = {"data": {str(assigned_port): expected_val}}
    core_v1.patch_namespaced_config_map("tcp-services", "ingress-nginx", patch_body)
    logger.info(f"Created TCP entry: port {assigned_port} → {svc_name}")

    return ("created", assigned_port)


def spawn_one(clients: tuple[Any, Any, Any], team: dict, challenge: dict) -> dict:
    """
    Spawn K8s resources for one team × challenge pair (secret, deployment, service, HTTP ingress).

    TCP ConfigMap entries are NOT created here — they must be added sequentially after
    this parallel phase to avoid read-modify-write races on the tcp-services ConfigMap.

    Args:
        clients: Tuple of (apps_v1, core_v1, net_v1) API instances
        team: Team dict with 'id' and 'name'
        challenge: Challenge manifest dict

    Returns:
        Summary dict: {team_id, challenge_id, status: "created"|"skipped"|"error", error: str|None}
    """
    apps_v1, core_v1, net_v1 = clients
    team_id = team["id"]
    challenge_id = challenge["id"]

    try:
        # Create secret
        create_secret(core_v1, team_id, challenge)

        # Create deployment
        create_deployment(apps_v1, team_id, challenge)

        # Create service (NodePort for TCP, ClusterIP for HTTP)
        create_service(core_v1, team_id, challenge)

        # No ingress for HTTP — uses NodePort + tcp-services (same as TCP)

        return {
            "team_id": team_id,
            "challenge_id": challenge_id,
            "status": "created",
            "error": None,
        }
    except Exception as e:
        logger.error(
            f"Error spawning {team_id}/{challenge_id}: {e}",
            exc_info=False,
        )
        return {
            "team_id": team_id,
            "challenge_id": challenge_id,
            "status": "error",
            "error": str(e),
        }


def main(ctfd_url: str, admin_token: str) -> None:
    """Entry point for bulk_spawn workflow."""
    logger.info("Starting bulk_spawn...")

    # Validate env var
    if not os.getenv("CTF_MASTER_SECRET"):
        raise ValueError("CTF_MASTER_SECRET env var not set")

    # Initialize K8s clients
    apps_v1, core_v1, net_v1 = init_k8s_client()
    clients = (apps_v1, core_v1, net_v1)

    # Fetch teams from CTFd
    teams = fetch_teams(ctfd_url, admin_token)
    logger.info(f"Fetched {len(teams)} teams")

    # Load challenge manifests (service challenges only — static/file challenges have no pods)
    # Bundle manifests have no top-level category; include them if they have a flags list
    # (bundle manifests are always service challenges by definition)
    challenges = [c for c in load_manifests()
                  if (c.get("category", "").lower() in {"web", "pwn", "misc", "crypto", "forensics", "reversing", "osint"}
                      or "flags" in c)
                  and c.get("type") != "static"]
    logger.info(f"Loaded {len(challenges)} service challenges")

    created = 0
    skipped = 0
    errors = 0

    # Phase 1 (parallel): secret + deployment + service + HTTP ingress
    # TCP challenges get secret/deployment/service here but NOT their ConfigMap entry.
    logger.info("Phase 1: spawning pods/services/ingresses in parallel...")
    futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for team in teams:
            for challenge in challenges:
                future = executor.submit(spawn_one, clients, team, challenge)
                futures[future] = (team["id"], challenge["id"])

        for future in concurrent.futures.as_completed(futures, timeout=600):
            try:
                result = future.result()
                if result["status"] == "created":
                    created += 1
                elif result["status"] == "skipped":
                    skipped += 1
                else:
                    errors += 1
            except concurrent.futures.TimeoutError:
                errors += 1
                team_id, challenge_id = futures[future]
                logger.error(f"Timeout spawning {team_id}/{challenge_id}")
            except Exception as e:
                errors += 1
                logger.error(f"Exception collecting result: {e}")

    # Phase 2 (sequential): TCP + HTTP ConfigMap entries — must NOT run in parallel.
    # Parallel read-modify-write on tcp-services ConfigMap causes port collisions
    # (validated: 10 parallel workers produced 43/100 entries instead of 100).
    tcp_challenges = [c for c in challenges if c.get("type") in ("tcp", "http")]
    if tcp_challenges:
        logger.info(
            f"Phase 2: registering TCP/HTTP ports sequentially "
            f"({len(teams)} teams × {len(tcp_challenges)} service challenges)..."
        )
        tcp_created = 0
        tcp_skipped = 0
        for team in teams:
            for challenge in tcp_challenges:
                try:
                    status, port = add_tcp_entry(core_v1, team["id"], challenge)
                    if status == "created":
                        tcp_created += 1
                    else:
                        tcp_skipped += 1
                except Exception as e:
                    errors += 1
                    logger.error(
                        f"Error adding TCP entry {team['id']}/{challenge['id']}: {e}"
                    )
        logger.info(
            f"TCP ports: {tcp_created} registered, {tcp_skipped} already present"
        )

    logger.info(f"Done: {created} created, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Pre-spawn all challenge pods for all teams")
    parser.add_argument("--ctfd-url", required=True, help="CTFd base URL")
    parser.add_argument("--token", required=True, help="CTFd admin API token")

    args = parser.parse_args()

    try:
        main(args.ctfd_url, args.token)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
