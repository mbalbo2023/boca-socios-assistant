"""Synthetic-only Option-A phase and recovery model; never opens Docker/blackbox."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios.browser_cutover_sequence import (
    CutoverCheckpoint,
    CutoverStage,
    ObservedContainer,
    TransitionObservation,
    advance_cutover,
    begin_cutover,
    verify_recovery_completion,
)
from boca_socios.browser_transition_contract import (
    ControllerEvidence,
    CutoverCoordinates,
    CutoverError,
    plan_transition,
)

LEGACY_SHA = "a" * 40
TARGET_SHA = "b" * 40
LEGACY_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
TARGET_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
LEGACY = "1" * 64
WORKER = "2" * 64
CANDIDATE = "3" * 64
ATTEMPT = "41920000000"
DATA = "boca-socios_boca_data"
KEY = "boca-socios_boca_key"
OWNER = "boca-socios_boca_owner"
IPC = "boca-socios_boca_browser_ipc"
BRIDGE = "boca-socios_boca_private"
MOUNTS = frozenset(
    {(DATA, "/data", True), (KEY, "/run/secrets", False), (OWNER, "/run/owner", False)}
)


def initial_checkpoint() -> CutoverCheckpoint:
    coordinates = CutoverCoordinates(
        legacy_sha=LEGACY_SHA,
        legacy_controller_image=LEGACY_IMAGE,
        target_main_sha=TARGET_SHA,
        target_release_sha=TARGET_SHA,
        target_controller_image=TARGET_IMAGE,
        target_browser_image=WORKER_IMAGE,
        original_container_id=LEGACY,
    )
    evidence = ControllerEvidence(
        inspected_container_id=LEGACY,
        project="boca-socios",
        service="controller",
        revision_sha=LEGACY_SHA,
        image=LEGACY_IMAGE,
        runtime_mode="simulation",
        engine_mode="off",
        browser_backend="off",
        port_binding="127.0.0.1:8443",
        running=True,
        containers=frozenset({LEGACY}),
        volumes=frozenset({DATA, KEY, OWNER}),
        networks=frozenset({BRIDGE}),
        mounted_volumes=MOUNTS,
    )
    return begin_cutover(plan_transition(coordinates, evidence), ATTEMPT)


def legacy(stage: CutoverStage) -> ObservedContainer:
    running = stage is CutoverStage.WORKER_READY
    return ObservedContainer(
        container_id=LEGACY,
        name=(
            "boca-socios-controller-1" if running else f"boca-socios-controller-legacy-{ATTEMPT}"
        ),
        project="boca-socios",
        service="controller",
        source_sha=LEGACY_SHA,
        image=LEGACY_IMAGE,
        attempt_id=None,
        running=running,
        healthy=running,
        runtime_mode="simulation",
        engine_mode="off",
        browser_backend="off",
        network_mode=BRIDGE,
        host_binding="127.0.0.1:8443",
        mounts=MOUNTS,
    )


def worker() -> ObservedContainer:
    return ObservedContainer(
        container_id=WORKER,
        name="boca-socios-browser-worker-1",
        project="boca-socios",
        service="browser-worker",
        source_sha=TARGET_SHA,
        image=WORKER_IMAGE,
        attempt_id=ATTEMPT,
        running=True,
        healthy=True,
        runtime_mode="simulation",
        engine_mode="off",
        browser_backend="off",
        network_mode="none",
        host_binding=None,
        mounts=frozenset({(IPC, "/run/boca-browser-ipc", True)}),
    )


def candidate() -> ObservedContainer:
    return ObservedContainer(
        container_id=CANDIDATE,
        name="boca-socios-controller-1",
        project="boca-socios",
        service="controller",
        source_sha=TARGET_SHA,
        image=TARGET_IMAGE,
        attempt_id=ATTEMPT,
        running=True,
        healthy=True,
        runtime_mode="simulation",
        engine_mode="off",
        browser_backend="ipc",
        network_mode=BRIDGE,
        host_binding="127.0.0.1:8443",
        mounts=MOUNTS | {(IPC, "/run/boca-browser-ipc", False)},
    )


def observation(stage: CutoverStage) -> TransitionObservation:
    old = None if stage is CutoverStage.ACCEPTED else legacy(stage)
    new = candidate() if stage in (CutoverStage.CANDIDATE_HEALTHY, CutoverStage.ACCEPTED) else None
    ids = {WORKER}
    if old is not None:
        ids.add(LEGACY)
    if new is not None:
        ids.add(CANDIDATE)
    return TransitionObservation(
        original=old,
        worker=worker(),
        candidate=new,
        all_container_ids=frozenset(ids),
        volumes=frozenset({DATA, KEY, OWNER, IPC}),
        networks=frozenset({BRIDGE}),
        loopback_owner_id=(
            LEGACY if stage is CutoverStage.WORKER_READY else CANDIDATE if new is not None else None
        ),
        persistent_custody_verified=True,
        synthetic_acceptance_passed=stage is CutoverStage.ACCEPTED,
    )


def to_stage(stage: CutoverStage) -> CutoverCheckpoint:
    checkpoint = initial_checkpoint()
    for next_stage in (
        CutoverStage.WORKER_READY,
        CutoverStage.LEGACY_PARKED,
        CutoverStage.CANDIDATE_HEALTHY,
        CutoverStage.ACCEPTED,
    ):
        checkpoint = advance_cutover(checkpoint, next_stage, observation(next_stage))
        if next_stage is stage:
            return checkpoint
    raise AssertionError("unreachable phase")


def test_all_four_explicit_transitions_keep_original_until_real_acceptance() -> None:
    checkpoint = initial_checkpoint()
    assert checkpoint.stage is CutoverStage.LEGACY_LIVE
    for stage in (
        CutoverStage.WORKER_READY,
        CutoverStage.LEGACY_PARKED,
        CutoverStage.CANDIDATE_HEALTHY,
        CutoverStage.ACCEPTED,
    ):
        checkpoint = advance_cutover(checkpoint, stage, observation(stage))
        assert not checkpoint.executable
        assert checkpoint.plan.legacy_source_sha != checkpoint.plan.target_source_sha
    assert checkpoint.worker_container_id == WORKER
    assert checkpoint.candidate_container_id == CANDIDATE


def test_candidate_phase_explicitly_allows_two_controller_labels_only_by_exact_ids() -> None:
    before = to_stage(CutoverStage.LEGACY_PARKED)
    during = observation(CutoverStage.CANDIDATE_HEALTHY)
    assert during.original is not None
    assert during.candidate is not None
    assert during.original.service == during.candidate.service == "controller"
    result = advance_cutover(before, CutoverStage.CANDIDATE_HEALTHY, during)
    assert result.stage is CutoverStage.CANDIDATE_HEALTHY


def test_parked_original_may_retain_stale_docker_health_metadata() -> None:
    before = to_stage(CutoverStage.WORKER_READY)
    observed = observation(CutoverStage.LEGACY_PARKED)
    assert observed.original is not None
    result = advance_cutover(
        before,
        CutoverStage.LEGACY_PARKED,
        replace(observed, original=replace(observed.original, healthy=True)),
    )
    assert result.stage is CutoverStage.LEGACY_PARKED


@pytest.mark.parametrize(
    "stage",
    [CutoverStage.LEGACY_LIVE, CutoverStage.CANDIDATE_HEALTHY, CutoverStage.ACCEPTED],
)
def test_phase_skips_and_replays_are_no_go(stage: CutoverStage) -> None:
    with pytest.raises(CutoverError):
        advance_cutover(initial_checkpoint(), stage, observation(CutoverStage.WORKER_READY))


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("all_container_ids", frozenset({LEGACY, WORKER, "4" * 64})),
        ("volumes", frozenset({DATA, KEY, IPC})),
        ("networks", frozenset({BRIDGE, "porota_network"})),
        ("loopback_owner_id", "4" * 64),
        ("persistent_custody_verified", False),
    ],
)
def test_worker_ready_fails_on_foreign_resources_or_port_owner(
    field: str, bad_value: object
) -> None:
    with pytest.raises(CutoverError):
        advance_cutover(
            initial_checkpoint(),
            CutoverStage.WORKER_READY,
            replace(observation(CutoverStage.WORKER_READY), **{field: bad_value}),
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("source_sha", LEGACY_SHA),
        ("image", LEGACY_IMAGE),
        ("attempt_id", "41920000001"),
        ("engine_mode", "on"),
        ("browser_backend", "off"),
        ("network_mode", "host"),
        ("host_binding", "0.0.0.0:8443"),
        ("mounts", MOUNTS),
        ("running", False),
        ("name", "boca-socios-controller-legacy-other"),
    ],
)
def test_candidate_identity_and_effective_config_must_be_exact(
    field: str, bad_value: object
) -> None:
    before = to_stage(CutoverStage.LEGACY_PARKED)
    observed = observation(CutoverStage.CANDIDATE_HEALTHY)
    assert observed.candidate is not None
    with pytest.raises(CutoverError):
        advance_cutover(
            before,
            CutoverStage.CANDIDATE_HEALTHY,
            replace(observed, candidate=replace(observed.candidate, **{field: bad_value})),
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("source_sha", LEGACY_SHA),
        ("network_mode", BRIDGE),
        ("mounts", MOUNTS),
        ("engine_mode", "on"),
        ("healthy", False),
        ("container_id", "4" * 64),
    ],
)
def test_worker_swap_or_isolation_change_is_rejected(field: str, bad_value: object) -> None:
    before = to_stage(CutoverStage.LEGACY_PARKED)
    observed = observation(CutoverStage.CANDIDATE_HEALTHY)
    assert observed.worker is not None
    with pytest.raises(CutoverError):
        advance_cutover(
            before,
            CutoverStage.CANDIDATE_HEALTHY,
            replace(observed, worker=replace(observed.worker, **{field: bad_value})),
        )


def test_original_cannot_be_removed_before_candidate_acceptance() -> None:
    before = to_stage(CutoverStage.LEGACY_PARKED)
    observed = observation(CutoverStage.CANDIDATE_HEALTHY)
    with pytest.raises(CutoverError):
        advance_cutover(
            before,
            CutoverStage.CANDIDATE_HEALTHY,
            replace(observed, original=None, all_container_ids=frozenset({CANDIDATE, WORKER})),
        )


def test_acceptance_receipt_is_mandatory_before_legacy_is_retired() -> None:
    before = to_stage(CutoverStage.CANDIDATE_HEALTHY)
    with pytest.raises(CutoverError):
        advance_cutover(
            before,
            CutoverStage.ACCEPTED,
            replace(observation(CutoverStage.ACCEPTED), synthetic_acceptance_passed=False),
        )


def test_new_attempt_requires_one_positive_numeric_id() -> None:
    checkpoint = initial_checkpoint()
    for bad in ("", "0", "-1", "0012", "4" * 25, "bad-uuid"):
        with pytest.raises(CutoverError):
            begin_cutover(checkpoint.plan, bad)


def recovered_observation() -> TransitionObservation:
    returned = replace(
        legacy(CutoverStage.WORKER_READY),
        name="boca-socios-controller-1",
    )
    return TransitionObservation(
        original=returned,
        worker=None,
        candidate=None,
        all_container_ids=frozenset({LEGACY}),
        volumes=frozenset({DATA, KEY, OWNER, IPC}),
        networks=frozenset({BRIDGE}),
        loopback_owner_id=LEGACY,
        persistent_custody_verified=True,
    )


def test_failed_handoff_only_counts_as_recovered_after_original_same_id_is_running() -> None:
    previous = to_stage(CutoverStage.CANDIDATE_HEALTHY)
    result = verify_recovery_completion(previous, recovered_observation())
    assert result == LEGACY


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("candidate", candidate()),
        ("worker", worker()),
        ("all_container_ids", frozenset({LEGACY, CANDIDATE})),
        ("loopback_owner_id", CANDIDATE),
        ("volumes", frozenset({DATA, OWNER, IPC})),
        ("persistent_custody_verified", False),
    ],
)
def test_uncertain_recovery_completion_never_claims_success(field: str, bad_value: object) -> None:
    previous = to_stage(CutoverStage.CANDIDATE_HEALTHY)
    with pytest.raises(CutoverError):
        verify_recovery_completion(previous, replace(recovered_observation(), **{field: bad_value}))


def test_recovery_cannot_claim_success_from_drifted_original() -> None:
    previous = to_stage(CutoverStage.CANDIDATE_HEALTHY)
    observed = recovered_observation()
    assert observed.original is not None
    with pytest.raises(CutoverError):
        verify_recovery_completion(
            previous,
            replace(observed, original=replace(observed.original, container_id="4" * 64)),
        )
