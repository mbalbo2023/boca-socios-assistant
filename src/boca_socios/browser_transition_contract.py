"""Inert safety contract for a future controller-only to browser IPC cutover.

The deployed singleton cannot be changed in place: the browser overlay changes
the controller's environment, mounts and restart policy. This module plans
neither Docker commands nor an automatic migration. It validates independently
observed, redacted coordinates before a *separate* reviewed host design may
consider interrupting the existing Boca controller. It never invokes the owner
controlled browser modules, Docker, a network endpoint or persistent storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[0-9a-f]{64}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_BROWSER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")

_DATA = "boca-socios_boca_data"
_KEY = "boca-socios_boca_key"
_OWNER = "boca-socios_boca_owner"
_TELEGRAM = "boca-socios_boca_telegram"
_BIND = "127.0.0.1:8443"
_PRIVATE = "boca-socios_boca_private"
_MOUNTS = frozenset(
    {
        (_DATA, "/data", True),
        (_KEY, "/run/secrets", False),
        (_OWNER, "/run/owner", False),
    }
)


class CutoverError(ValueError):
    """A future cutover must stop before any effect because identity is uncertain."""


@dataclass(frozen=True)
class CutoverCoordinates:
    main_sha: str
    release_sha: str
    controller_image: str
    browser_image: str
    original_container_id: str


@dataclass(frozen=True)
class ControllerEvidence:
    """Explicitly redacted *inputs*, not a replacement for Docker inspection.

    A future host workflow must derive and authenticate these values from
    read-only, positive-identity evidence in the dedicated Boca rootless daemon.
    Caller assertions alone are never authority to create/remove containers.
    """

    inspected_container_id: str
    project: str
    service: str
    revision_sha: str
    image: str
    runtime_mode: str
    engine_mode: str
    browser_backend: str
    port_binding: str
    running: bool
    containers: frozenset[str]
    volumes: frozenset[str]
    networks: frozenset[str]
    mounted_volumes: frozenset[tuple[str, str, bool]]


@dataclass(frozen=True)
class InertTransitionPlan:
    original_container_id: str
    protected_volumes: frozenset[str]
    reserved_host_binding: str = _BIND
    requires_explicit_approval: bool = True
    executable: bool = False
    permitted_effects: tuple[()] = ()


@dataclass(frozen=True)
class RecoveryEvidence:
    original_container_id: str
    original_verified: bool
    original_stopped: bool
    candidate_stopped: bool
    worker_stopped: bool
    unknown_resources: frozenset[str]
    volumes: frozenset[str]
    owner_key_data_unchanged: bool


@dataclass(frozen=True)
class InertRecoveryDecision:
    """Approval-free design hint, not a shell operation or recovery receipt."""

    original_container_id: str
    only_action: str = "restart_exact_original_controller"
    delete_volumes: frozenset[str] = frozenset()


def plan_transition(
    coordinates: CutoverCoordinates, observed: ControllerEvidence
) -> InertTransitionPlan:
    """Reject drift before proposing any controller-to-worker cutover design.

    This is a *second* pure contract check. The protected host operation must
    also prove actual Docker metadata, owner/key/data integrity, image digests,
    no foreign objects and loopback ownership independently and immediately
    before any effect. Nothing returned here authorizes an effect.
    """
    if (
        not _SHA.fullmatch(coordinates.main_sha)
        or coordinates.release_sha != coordinates.main_sha
        or not _CONTROLLER.fullmatch(coordinates.controller_image)
        or not _BROWSER.fullmatch(coordinates.browser_image)
        or not _ID.fullmatch(coordinates.original_container_id)
    ):
        raise CutoverError("transition source/release/image coordinates are not immutable")
    if (
        observed.inspected_container_id != coordinates.original_container_id
        or observed.containers != frozenset({coordinates.original_container_id})
        or observed.project != "boca-socios"
        or observed.service != "controller"
        or observed.revision_sha != coordinates.main_sha
        or observed.image != coordinates.controller_image
        or observed.runtime_mode != "simulation"
        or observed.engine_mode != "off"
        or observed.browser_backend != "off"
        or observed.port_binding != _BIND
        or observed.running is not True
        or observed.networks != frozenset({_PRIVATE})
        or observed.mounted_volumes != _MOUNTS
    ):
        raise CutoverError("existing singleton identity or isolation is unverified")
    allowed = frozenset({_DATA, _KEY, _OWNER})
    if observed.volumes not in (allowed, allowed | {_TELEGRAM}):
        raise CutoverError("persistent Boca volume namespace differs")
    return InertTransitionPlan(
        original_container_id=coordinates.original_container_id,
        protected_volumes=observed.volumes,
    )


def verify_legacy_recovery(
    plan: InertTransitionPlan, observed: RecoveryEvidence
) -> InertRecoveryDecision:
    """Allow only a proposal to resume the verified old controller.

    A physical operation would additionally need fresh Docker inspection,
    exact image/labels/volumes/network checks and an explicit gate. In
    particular, this function neither deletes anything nor starts a process.
    """
    if (
        plan.executable
        or plan.permitted_effects
        or not plan.requires_explicit_approval
        or observed.original_container_id != plan.original_container_id
        or observed.original_verified is not True
        or observed.original_stopped is not True
        or observed.candidate_stopped is not True
        or observed.worker_stopped is not True
        or observed.unknown_resources
        or observed.volumes != plan.protected_volumes
        or observed.owner_key_data_unchanged is not True
    ):
        raise CutoverError("original-controller recovery has uncertain identity or custody")
    return InertRecoveryDecision(original_container_id=plan.original_container_id)
