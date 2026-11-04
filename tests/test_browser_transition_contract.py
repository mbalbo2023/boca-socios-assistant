"""Inert controller-to-browser transition gates; no Docker or blackbox execution."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios.browser_transition_contract import (
    ControllerEvidence,
    CutoverCoordinates,
    CutoverError,
    RecoveryEvidence,
    plan_transition,
    verify_legacy_recovery,
)

SHA = "a" * 40
TARGET_SHA = "e" * 40
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
TARGET_CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64
CONTAINER = "d" * 64
DATA = "boca-socios_boca_data"
KEY = "boca-socios_boca_key"
OWNER = "boca-socios_boca_owner"
PRIVATE = "boca-socios_boca_private"


def coordinates() -> CutoverCoordinates:
    return CutoverCoordinates(
        legacy_sha=SHA,
        legacy_controller_image=CONTROLLER,
        target_main_sha=TARGET_SHA,
        target_release_sha=TARGET_SHA,
        target_controller_image=TARGET_CONTROLLER,
        target_browser_image=BROWSER,
        original_container_id=CONTAINER,
    )


def evidence() -> ControllerEvidence:
    return ControllerEvidence(
        inspected_container_id=CONTAINER,
        project="boca-socios",
        service="controller",
        revision_sha=SHA,
        image=CONTROLLER,
        runtime_mode="simulation",
        engine_mode="off",
        browser_backend="off",
        port_binding="127.0.0.1:8443",
        running=True,
        containers=frozenset({CONTAINER}),
        volumes=frozenset({DATA, KEY, OWNER}),
        networks=frozenset({PRIVATE}),
        mounted_volumes=frozenset(
            {(DATA, "/data", True), (KEY, "/run/secrets", False), (OWNER, "/run/owner", False)}
        ),
    )


def test_exact_existing_controller_yields_only_inert_scoped_plan() -> None:
    plan = plan_transition(coordinates(), evidence())
    assert plan.original_container_id == CONTAINER
    assert plan.legacy_source_sha == SHA
    assert plan.target_source_sha == TARGET_SHA
    assert plan.protected_volumes == frozenset({DATA, KEY, OWNER})
    assert plan.reserved_host_binding == "127.0.0.1:8443"
    assert plan.requires_explicit_approval
    assert not plan.executable
    assert plan.permitted_effects == ()


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("legacy_sha", "not-a-sha"),
        ("target_main_sha", "not-a-sha"),
        ("target_release_sha", SHA),
        ("legacy_controller_image", BROWSER),
        ("target_controller_image", CONTROLLER),
        ("target_controller_image", BROWSER),
        ("target_browser_image", CONTROLLER),
        ("original_container_id", "not-a-container"),
    ],
)
def test_immutable_coordinates_drift_is_no_go(change: str, value: str) -> None:
    with pytest.raises(CutoverError):
        plan_transition(replace(coordinates(), **{change: value}), evidence())


def test_valid_new_release_must_not_be_confused_with_installed_legacy_revision() -> None:
    assert coordinates().legacy_sha != coordinates().target_main_sha
    plan = plan_transition(coordinates(), evidence())
    assert plan.legacy_source_sha == SHA
    assert plan.target_source_sha == TARGET_SHA
    with pytest.raises(CutoverError):
        plan_transition(
            replace(coordinates(), target_release_sha=SHA),
            replace(evidence(), revision_sha=TARGET_SHA),
        )


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("project", "other-stack"),
        ("service", "unknown"),
        ("revision_sha", "e" * 40),
        ("image", "other-image"),
        ("runtime_mode", "live"),
        ("engine_mode", "on"),
        ("browser_backend", "ipc"),
        ("port_binding", "0.0.0.0:8443"),
        ("running", False),
        ("inspected_container_id", "e" * 64),
        ("containers", frozenset({CONTAINER, "e" * 64})),
        ("volumes", frozenset({DATA, KEY, OWNER, "foreign_volume"})),
        ("networks", frozenset({PRIVATE, "foreign_network"})),
        ("mounted_volumes", frozenset({(DATA, "/data", True)})),
    ],
)
def test_foreign_or_drifted_topology_fails_before_any_transition(
    change: str, value: object
) -> None:
    with pytest.raises(CutoverError):
        plan_transition(coordinates(), replace(evidence(), **{change: value}))


def test_optional_existing_telegram_volume_is_preserved_not_recreated() -> None:
    observation = replace(evidence(), volumes=evidence().volumes | {"boca-socios_boca_telegram"})
    plan = plan_transition(coordinates(), observation)
    assert "boca-socios_boca_telegram" in plan.protected_volumes
    assert not plan.executable


def test_recovery_requires_original_controller_identity_and_preserved_data() -> None:
    plan = plan_transition(coordinates(), evidence())
    verified = RecoveryEvidence(
        original_container_id=CONTAINER,
        original_verified=True,
        original_stopped=True,
        candidate_stopped=True,
        worker_stopped=True,
        unknown_resources=frozenset(),
        volumes=frozenset({DATA, KEY, OWNER}),
        owner_key_data_unchanged=True,
    )
    receipt = verify_legacy_recovery(plan, verified)
    assert receipt.original_container_id == CONTAINER
    assert receipt.only_action == "restart_exact_original_controller"
    assert receipt.delete_volumes == frozenset()


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("original_container_id", "e" * 64),
        ("original_verified", False),
        ("original_stopped", False),
        ("candidate_stopped", False),
        ("worker_stopped", False),
        ("unknown_resources", frozenset({"foreign"})),
        ("volumes", frozenset({DATA, KEY})),
        ("owner_key_data_unchanged", False),
    ],
)
def test_uncertain_midcutover_recovery_refuses_any_action(change: str, value: object) -> None:
    plan = plan_transition(coordinates(), evidence())
    observed = RecoveryEvidence(
        original_container_id=CONTAINER,
        original_verified=True,
        original_stopped=True,
        candidate_stopped=True,
        worker_stopped=True,
        unknown_resources=frozenset(),
        volumes=frozenset({DATA, KEY, OWNER}),
        owner_key_data_unchanged=True,
    )
    with pytest.raises(CutoverError):
        verify_legacy_recovery(plan, replace(observed, **{change: value}))
