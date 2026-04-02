#!/usr/bin/env python3
"""
api.py - FastAPI controller for team challenge activation/deactivation.

Endpoints:
  POST   /activate          - Activate a challenge for a team
  GET    /status/{team_id}  - Get status of all challenges for a team
  POST   /deactivate        - Deactivate a challenge for a team
  GET    /health            - Health check (no auth)
"""

import os
import secrets
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from kubernetes.client.rest import ApiException

from k8s_client import init_k8s_client
from naming import deployment_name, service_name
from exceptions import ChallengeNotFound, MaxInstancesExceeded, ControllerKeyInvalid
from manifest_loader import load_manifests

logger = logging.getLogger(__name__)

# Cache manifests in memory for URL building
_manifest_cache: Optional[dict] = None


def get_challenge_manifests() -> dict:
    """Load and cache challenge manifests."""
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = {c["id"]: c for c in load_manifests()}
    return _manifest_cache


# Exception handlers
def challenge_not_found_handler(request: Request, exc: ChallengeNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Challenge not found"})


def max_instances_handler(request: Request, exc: MaxInstancesExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Max 4 active instances reached. Stop one to continue."},
    )


def controller_key_invalid_handler(request: Request, exc: ControllerKeyInvalid) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Invalid controller key"})


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize K8s clients and validate environment."""
    if not os.getenv("CTF_MASTER_SECRET"):
        raise ValueError("CTF_MASTER_SECRET env var not set")
    if not os.getenv("CONTROLLER_KEY"):
        raise ValueError("CONTROLLER_KEY env var not set")

    apps_v1, core_v1, _ = init_k8s_client()
    app.state.apps_v1 = apps_v1
    app.state.core_v1 = core_v1

    logger.info("Controller API started")
    yield
    logger.info("Controller API shutdown")


# Create FastAPI app
app = FastAPI(lifespan=lifespan)

# Register exception handlers
app.add_exception_handler(ChallengeNotFound, challenge_not_found_handler)
app.add_exception_handler(MaxInstancesExceeded, max_instances_handler)
app.add_exception_handler(ControllerKeyInvalid, controller_key_invalid_handler)


# Request/Response models
class ActivateRequest(BaseModel):
    team_id: str
    challenge_id: str


class DeactivateRequest(BaseModel):
    team_id: str
    challenge_id: str


class ActivateResponse(BaseModel):
    status: str
    url: Optional[str] = None


class DeactivateResponse(BaseModel):
    status: str


class ChallengeStatus(BaseModel):
    challenge_id: str
    status: str
    url: Optional[str] = None
    activated_at: Optional[str] = None


class StatusResponse(BaseModel):
    challenges: list[ChallengeStatus]


# Auth dependency
def verify_controller_key(x_controller_key: str = Header(...)) -> None:
    """Verify X-Controller-Key header matches CONTROLLER_KEY env var."""
    expected = os.getenv("CONTROLLER_KEY", "")
    if not secrets.compare_digest(x_controller_key.encode(), expected.encode()):
        raise ControllerKeyInvalid()


def clear_activation_annotation(apps_v1: Any, dep_name: str) -> None:
    """
    Clear the ctf/activated-at annotation and set replicas to 0.

    Sets annotation value to null (not just omits it) so K8s strategic merge
    patch actually removes the key rather than leaving it unchanged.
    Idempotent: safe to call multiple times.
    """
    patch_body = {
        "metadata": {"annotations": {"ctf/activated-at": None}},
        "spec": {"replicas": 0},
    }
    apps_v1.patch_namespaced_deployment(dep_name, "challenges", patch_body)


def build_challenge_url(core_v1: Any, team_id: str, challenge_id: str) -> Optional[str]:
    """
    Build the challenge URL for a team.

    For HTTP challenges: https://team-{team_id}-{challenge_id}.challenges.infodays.net
    For TCP challenges: nc challenges.infodays.net {port}
    Returns None only if TCP port is not yet assigned (race condition window during bulk_spawn).
    """
    manifests = get_challenge_manifests()
    challenge = manifests.get(challenge_id)

    if not challenge:
        logger.warning(f"Manifest not found for challenge_id={challenge_id}")
        return None

    if challenge.get("type") == "http":
        return f"https://team-{team_id}-{challenge_id}.challenges.infodays.net"

    # TCP: get NodePort from the challenge service + any node's external IP
    try:
        svc_name = service_name(team_id, challenge_id)
        svc = core_v1.read_namespaced_service(svc_name, "challenges")
        node_port = svc.spec.ports[0].node_port
        if not node_port:
            logger.warning(f"NodePort not assigned yet for {svc_name}")
            return None

        return f"nc challenges.infodays.net {node_port}"
    except ApiException as e:
        logger.error(f"Failed to build TCP URL for {svc_name}: {e.status} {e.reason}")
        return None


@app.post("/activate", response_model=ActivateResponse)
async def activate(req: ActivateRequest, request: Request, _=Depends(verify_controller_key)):
    """Activate a challenge for a team."""
    apps_v1 = request.app.state.apps_v1
    core_v1 = request.app.state.core_v1

    # Count active pods for this team
    deploys = apps_v1.list_namespaced_deployment(
        "challenges", label_selector=f"team={req.team_id},managed-by=ctf-controller"
    ).items
    active_count = sum(1 for d in deploys if d.spec.replicas == 1)

    # Check 4-pod cap
    if active_count >= 4:
        raise MaxInstancesExceeded()

    # Resolve deployment name and verify it exists
    dep_name = deployment_name(req.team_id, req.challenge_id)
    try:
        apps_v1.read_namespaced_deployment(dep_name, "challenges")
    except ApiException as e:
        if e.status == 404:
            raise ChallengeNotFound()
        raise

    # Build patch: set replicas=1 and record activation timestamp
    patch_body = {
        "spec": {"replicas": 1},
        "metadata": {"annotations": {"ctf/activated-at": datetime.now(timezone.utc).isoformat()}},
    }
    apps_v1.patch_namespaced_deployment(dep_name, "challenges", patch_body)

    url = build_challenge_url(core_v1, req.team_id, req.challenge_id)
    logger.info(f"Activated {dep_name}")
    return {"status": "starting", "url": url}


@app.post("/deactivate", response_model=DeactivateResponse)
async def deactivate(req: DeactivateRequest, request: Request, _=Depends(verify_controller_key)):
    """Deactivate a challenge for a team."""
    apps_v1 = request.app.state.apps_v1

    dep_name = deployment_name(req.team_id, req.challenge_id)
    try:
        apps_v1.read_namespaced_deployment(dep_name, "challenges")
    except ApiException as e:
        if e.status == 404:
            raise ChallengeNotFound()
        raise

    clear_activation_annotation(apps_v1, dep_name)
    logger.info(f"Deactivated {dep_name}")
    return {"status": "suspended"}


@app.get("/status/{team_id}", response_model=StatusResponse)
async def get_status(team_id: str, request: Request, _=Depends(verify_controller_key)):
    """Get status of all challenges for a team. Returns empty list for unknown teams."""
    apps_v1 = request.app.state.apps_v1
    core_v1 = request.app.state.core_v1

    deploys = apps_v1.list_namespaced_deployment(
        "challenges", label_selector=f"team={team_id},managed-by=ctf-controller"
    ).items

    if not deploys:
        return {"challenges": []}

    challenges = []
    for deploy in deploys:
        challenge_id = deploy.metadata.labels.get("challenge")
        replicas = deploy.spec.replicas or 0
        activated_at = (deploy.metadata.annotations or {}).get("ctf/activated-at", "")

        # Compute status
        if replicas == 1:
            status = "running"
        elif replicas == 0 and activated_at:
            status = "suspended"
        elif replicas == 0 and not activated_at:
            status = "fresh"
        else:
            status = "unknown"

        url = build_challenge_url(core_v1, team_id, challenge_id) if replicas == 1 else None

        challenges.append(
            ChallengeStatus(
                challenge_id=challenge_id,
                status=status,
                url=url,
                activated_at=activated_at if activated_at else None,
            )
        )

    return {"challenges": challenges}


@app.get("/health")
async def health_check():
    """Health check endpoint - no auth required."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=5000)
