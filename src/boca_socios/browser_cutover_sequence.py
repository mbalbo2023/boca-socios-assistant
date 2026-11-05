"""Pure Option-A transition checkpoints for an already-installed BETA.

An eventual protected host adapter must collect and authenticate fresh Docker
inspection records, release manifests and acceptance receipts before calling
these functions. Caller-provided values are not authority for any host action.
This module deliberately contains no subprocess, network or filesystem I/O,
no Docker command executor and no browser/owner-blackbox import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from boca_socios.browser_transition_contract import CutoverError, InertTransitionPlan

_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_BINDING = "127.0.0.1:8443"
_BRIDGE = "boca-socios_boca_private"
_IPC = "boca-socios_boca_browser_ipc"
_OLD_MOUNTS = frozenset(
    {
        ("boca-socios_boca_data", "/data", True),
        ("boca-socios_boca_key", "/run/secrets", False),
        ("boca-socios_boca_owner", "/run/owner", False),
    }
)
_IPC_CONTROLLER = (_IPC, "/run/boca-browser-ipc", False)
_IPC_WORKER = (_IPC, "/run/boca-browser-ipc", True)


class CutoverStage(Enum):
    """Strictly increasing, deliberately non-retryable design checkpoints."""

    LEGACY_LIVE = "legacy-live"
    WORKER_READY = "worker-ready"
    LEGACY_PARKED = "legacy-parked"
    CANDIDATE_HEALTHY = "candidate-healthy"
    ACCEPTED = "accepted"


@dataclass(frozen=True)
class ObservedContainer:
    container_id: str
    name: str
    project: str
    service: str
    source_sha: str
    image: str
    attempt_id: str | None
    running: bool
    healthy: bool
    runtime_mode: str
    engine_mode: str
    browser_backend: str
    network_mode: str
    host_binding: str | None
    mounts: frozenset[tuple[str, str, bool]]


@dataclass(frozen=True)
class TransitionObservation:
    """Sanitized host state; host-side collection is a *separate* gate."""

    original: ObservedContainer | None
    worker: ObservedContainer | None
    candidate: ObservedContainer | None
    all_container_ids: frozenset[str]
    volumes: frozenset[str]
    networks: frozenset[str]
    loopback_owner_id: str | None
    persistent_custody_verified: bool
    synthetic_acceptance_passed: bool = False


@dataclass(frozen=True)
class CutoverCheckpoint:
    plan: InertTransitionPlan
    attempt_id: str
    stage: CutoverStage
    worker_container_id: str | None = None
    candidate_container_id: str | None = None
    executable: bool = False


def begin_cutover(plan: InertTransitionPlan, attempt_id: str) -> CutoverCheckpoint:
    """Bind the legacy and target identities before planning any phase."""
    if (
        not _ATTEMPT.fullmatch(attempt_id)
        or not _CONTAINER_ID.fullmatch(plan.original_container_id)
        or plan.executable
        or plan.permitted_effects
        or not plan.requires_explicit_approval
    ):
        raise CutoverError("cutover attempt is not uniquely and inertly bound")
    return CutoverCheckpoint(plan=plan, attempt_id=attempt_id, stage=CutoverStage.LEGACY_LIVE)


def _check_container(
    observed: ObservedContainer,
    *,
    name: str,
    service: str,
    source_sha: str,
    image: str,
    attempt_id: str | None,
    running: bool,
    backend: str,
    network: str,
    port: str | None,
    mounts: frozenset[tuple[str, str, bool]],
) -> None:
    if (
        not _CONTAINER_ID.fullmatch(observed.container_id)
        or observed.name != name
        or observed.project != "boca-socios"
        or observed.service != service
        or observed.source_sha != source_sha
        or observed.image != image
        or observed.attempt_id != attempt_id
        or observed.running is not running
        or type(observed.healthy) is not bool
        or (running and observed.healthy is not True)
        or observed.runtime_mode != "simulation"
        or observed.engine_mode != "off"
        or observed.browser_backend != backend
        or observed.network_mode != network
        or observed.host_binding != port
        or observed.mounts != mounts
    ):
        raise CutoverError("transitional Docker identity or isolation differs")


def advance_cutover(
    checkpoint: CutoverCheckpoint,
    stage: CutoverStage,
    observed: TransitionObservation,
) -> CutoverCheckpoint:
    """Fail closed on every handoff state, including two transient controller labels.

    No commands are returned. A protected host adapter must separately verify
    raw metadata, the previous checkpoint and actual phase effects.
    """
    ordered = (
        CutoverStage.LEGACY_LIVE,
        CutoverStage.WORKER_READY,
        CutoverStage.LEGACY_PARKED,
        CutoverStage.CANDIDATE_HEALTHY,
        CutoverStage.ACCEPTED,
    )
    if (
        checkpoint.executable
        or not isinstance(stage, CutoverStage)
        or ordered.index(stage) != ordered.index(checkpoint.stage) + 1
        or observed.persistent_custody_verified is not True
        or observed.volumes != checkpoint.plan.protected_volumes | {_IPC}
        or observed.networks != frozenset({_BRIDGE})
    ):
        raise CutoverError("cutover phase skipped, replayed or persistent inventory drifted")

    original = observed.original
    worker = observed.worker
    candidate = observed.candidate
    if worker is None:
        raise CutoverError("cutover requires the verified IPC worker")
    _check_container(
        worker,
        name="boca-socios-browser-worker-1",
        service="browser-worker",
        source_sha=checkpoint.plan.target_source_sha,
        image=checkpoint.plan.target_browser_image,
        attempt_id=checkpoint.attempt_id,
        running=True,
        backend="off",
        network="none",
        port=None,
        mounts=frozenset({_IPC_WORKER}),
    )
    if (
        checkpoint.worker_container_id is not None
        and worker.container_id != checkpoint.worker_container_id
    ):
        raise CutoverError("IPC worker was swapped during handoff")

    if stage is not CutoverStage.ACCEPTED:
        if original is None or original.container_id != checkpoint.plan.original_container_id:
            raise CutoverError("original controller was removed before acceptance")
        legacy_running = stage is CutoverStage.WORKER_READY
        _check_container(
            original,
            name=(
                "boca-socios-controller-1"
                if legacy_running
                else f"boca-socios-controller-legacy-{checkpoint.attempt_id}"
            ),
            service="controller",
            source_sha=checkpoint.plan.legacy_source_sha,
            image=checkpoint.plan.legacy_controller_image,
            attempt_id=None,
            running=legacy_running,
            backend="off",
            network=_BRIDGE,
            port=_BINDING,
            mounts=_OLD_MOUNTS,
        )
    elif original is not None:
        raise CutoverError("legacy controller must be explicitly retired after acceptance")

    candidate_expected = stage in (CutoverStage.CANDIDATE_HEALTHY, CutoverStage.ACCEPTED)
    if candidate_expected:
        if candidate is None:
            raise CutoverError("candidate controller is missing")
        _check_container(
            candidate,
            name="boca-socios-controller-1",
            service="controller",
            source_sha=checkpoint.plan.target_source_sha,
            image=checkpoint.plan.target_controller_image,
            attempt_id=checkpoint.attempt_id,
            running=True,
            backend="ipc",
            network=_BRIDGE,
            port=_BINDING,
            mounts=_OLD_MOUNTS | {_IPC_CONTROLLER},
        )
        if (
            checkpoint.candidate_container_id is not None
            and candidate.container_id != checkpoint.candidate_container_id
        ):
            raise CutoverError("candidate controller was swapped after health proof")
    elif candidate is not None:
        raise CutoverError("candidate must not appear before parking legacy")

    permitted_ids = {worker.container_id}
    if original is not None:
        permitted_ids.add(original.container_id)
    if candidate is not None:
        permitted_ids.add(candidate.container_id)
    if len(permitted_ids) != 1 + int(original is not None) + int(candidate is not None):
        raise CutoverError("cutover component identities overlap")
    if observed.all_container_ids != frozenset(permitted_ids):
        raise CutoverError("unexpected container or ambiguous Compose service topology")
    expected_port_owner = (
        original.container_id
        if stage is CutoverStage.WORKER_READY and original is not None
        else candidate.container_id
        if candidate is not None
        else None
    )
    if observed.loopback_owner_id != expected_port_owner:
        raise CutoverError("localhost 8443 owner changed or was acquired by another service")
    if stage is CutoverStage.ACCEPTED and observed.synthetic_acceptance_passed is not True:
        raise CutoverError("retiring original requires genuine candidate acceptance")

    return CutoverCheckpoint(
        plan=checkpoint.plan,
        attempt_id=checkpoint.attempt_id,
        stage=stage,
        worker_container_id=worker.container_id,
        candidate_container_id=candidate.container_id if candidate is not None else None,
    )


def verify_recovery_completion(
    checkpoint: CutoverCheckpoint, observed: TransitionObservation
) -> str:
    """Require a physically restored original singleton before claiming recovery.

    Only a future host collector can provide trusted records. Retaining the
    unused IPC volume is acceptable; data/key/owner are never optional.
    """
    if checkpoint.stage not in (
        CutoverStage.WORKER_READY,
        CutoverStage.LEGACY_PARKED,
        CutoverStage.CANDIDATE_HEALTHY,
    ):
        raise CutoverError("recovery checkpoint does not represent a reversible cutover")
    original = observed.original
    if (
        checkpoint.executable
        or observed.persistent_custody_verified is not True
        or original is None
        or original.container_id != checkpoint.plan.original_container_id
        or observed.worker is not None
        or observed.candidate is not None
        or observed.all_container_ids != frozenset({checkpoint.plan.original_container_id})
        or observed.volumes
        not in (checkpoint.plan.protected_volumes, checkpoint.plan.protected_volumes | {_IPC})
        or observed.networks != frozenset({_BRIDGE})
        or observed.loopback_owner_id != original.container_id
    ):
        raise CutoverError("recovery is not the exact original running singleton")
    _check_container(
        original,
        name="boca-socios-controller-1",
        service="controller",
        source_sha=checkpoint.plan.legacy_source_sha,
        image=checkpoint.plan.legacy_controller_image,
        attempt_id=None,
        running=True,
        backend="off",
        network=_BRIDGE,
        port=_BINDING,
        mounts=_OLD_MOUNTS,
    )
    return original.container_id
