"""R280: preserve the exact inode identity when PARK moves the control path."""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade_backend as historical
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios.host_boca_pair_stage import PairSources
from test_host_boca_successor_physical_v2 import _bound, _io_for_graph


@pytest.fixture
def held_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    directory = tmp_path / "lease"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", directory)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    with cleanup.protected_boca_job_lease(_bound().plan.attempt_id) as lease:
        yield lease


def test_parked_control_identity_path_is_pinned_and_cannot_escape() -> None:
    plan = _bound().plan
    assert str(retained.control_identity_path("control_socket_directory")) == (
        "/home/boca-deploy/.boca-on-demand/socket"
    )
    assert str(
        retained.control_identity_path(f"parked_control_socket_directory:{plan.attempt_id}")
    ) == (f"/home/boca-deploy/.boca-on-demand-parked-{plan.attempt_id}/socket")
    for invalid in (
        "parked_control_socket_directory:../../etc",
        "parked_control_socket_directory:0",
        "parked_control_socket_directory:123/456",
        "parked_control_socket_directory:123\n",
    ):
        with pytest.raises(retained.ResourceNoGo):
            retained.control_identity_path(invalid)


def test_source_retained_identity_remains_phase_correct_through_commit(
    held_lease: cleanup.BocaJobLease,
) -> None:
    bound = _bound()
    plan = bound.plan
    old_inode = bound.custody.control_directory_inode_sha256
    new_inode = "a" * 64
    assert old_inode != new_inode
    reads: list[str] = []
    active_phase = "NEW"

    def control(name: str) -> str:
        reads.append(name)
        if name == f"parked_control_socket_directory:{plan.attempt_id}":
            return old_inode
        if name == "control_socket_directory":
            return old_inode if active_phase in ("NEW", "STAGED", "RESTORED") else new_inode
        raise AssertionError("unexpected control path selector")

    source = (b"base", b"overlay", b"seccomp")
    pairs = PairSources(
        *source,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(source[0]).hexdigest(),
        overlay_sha=hashlib.sha256(source[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(source[2]).hexdigest(),
    )
    integrator = physical.PhysicalSuccessorIntegrations(
        plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        control_identity_reader=control,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        pairs, bound.retained, integrations=integrator, gate=None
    )
    integrator.bind_backend(backend)

    for active_phase in (
        "NEW",
        "STAGED",
        "PARKED",
        "WORKER",
        "CONTROLLER",
        "ACCEPTED_COLD",
        "BOUND",
        "RETIRED",
    ):
        worker_id = (
            "e" * 64
            if active_phase in ("WORKER", "CONTROLLER", "ACCEPTED_COLD", "BOUND", "RETIRED")
            else None
        )
        controller_id = (
            "f" * 64
            if active_phase in ("CONTROLLER", "ACCEPTED_COLD", "BOUND", "RETIRED")
            else None
        )
        graph = physical.expected_transition_graph(
            plan,
            active_phase,
            worker_id=worker_id,
            controller_id=controller_id,
            previous_observation=bound.original_pair_receipt,
        )
        backend.state = active_phase
        backend.worker_id = worker_id
        backend.controller_id = controller_id
        integrator.retained_io = _io_for_graph(
            graph, plan, running_old=active_phase in ("NEW", "STAGED")
        )
        reads.clear()
        assert integrator.retained_resources(plan, held_lease) == bound.retained
        expected = (
            ["control_socket_directory"]
            if active_phase in ("NEW", "STAGED", "RETIRED")
            else [f"parked_control_socket_directory:{plan.attempt_id}"]
            if active_phase in ("PARKED", "WORKER")
            else [f"parked_control_socket_directory:{plan.attempt_id}", "control_socket_directory"]
        )
        assert sorted(set(reads)) == sorted(expected)


def test_recovery_must_return_to_original_canonical_control_path(
    held_lease: cleanup.BocaJobLease,
) -> None:
    bound = _bound()
    plan = bound.plan
    graph = physical.expected_transition_graph(
        plan, "RESTORED", previous_observation=bound.original_pair_receipt
    )
    asks: list[str] = []

    def canonical(name: str) -> str:
        asks.append(name)
        return bound.custody.control_directory_inode_sha256

    sources = (b"base", b"overlay", b"seccomp")
    pairs = PairSources(
        *sources,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(sources[0]).hexdigest(),
        overlay_sha=hashlib.sha256(sources[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(sources[2]).hexdigest(),
    )
    integrator = physical.PhysicalSuccessorIntegrations(
        plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=_io_for_graph(graph, plan, running_old=True),
        control_identity_reader=canonical,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        pairs, bound.retained, integrations=integrator, gate=None
    )
    integrator.bind_backend(backend)
    backend.state = "RESTORED"
    assert integrator.retained_resources(plan, held_lease) == bound.retained
    assert asks == ["control_socket_directory", "control_socket_directory"]


def test_parked_inode_guard_allows_exact_old_restore_but_never_drift(
    held_lease: cleanup.BocaJobLease,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = _bound()
    plan = bound.plan
    phase = "PARKED"
    calls: list[str] = []
    drift = False

    def reader(name: str) -> str:
        calls.append(name)
        if name == f"parked_control_socket_directory:{plan.attempt_id}":
            return "a" * 64 if drift else bound.custody.control_directory_inode_sha256
        if name == "control_socket_directory" and phase == "RESTORED":
            return bound.custody.control_directory_inode_sha256
        raise AssertionError("wrong path during compensation")

    src = (b"base", b"overlay", b"seccomp")
    pairs = PairSources(
        *src,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(src[0]).hexdigest(),
        overlay_sha=hashlib.sha256(src[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(src[2]).hexdigest(),
    )
    parked_graph = physical.expected_transition_graph(
        plan, "PARKED", previous_observation=bound.original_pair_receipt
    )
    integrations = physical.PhysicalSuccessorIntegrations(
        plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=_io_for_graph(parked_graph, plan, running_old=False),
        control_identity_reader=reader,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        pairs, bound.retained, integrations=integrations, gate=None
    )
    integrations.bind_backend(backend)
    backend.state = phase
    invocations: list[str] = []

    def exact_restore(*_args: object) -> bool:
        nonlocal phase
        invocations.append("RESTORE")
        phase = "RESTORED"
        backend.state = phase
        restored_graph = physical.expected_transition_graph(
            plan, phase, previous_observation=bound.original_pair_receipt
        )
        integrations.retained_io = _io_for_graph(restored_graph, plan, running_old=True)
        return True

    monkeypatch.setattr(historical.RootlessPairUpgradeBackend, "restore_old", exact_restore)
    assert backend.restore_old(plan, held_lease) is True
    assert invocations == ["RESTORE"]
    assert calls[:2] == [f"parked_control_socket_directory:{plan.attempt_id}"] * 2
    assert calls[-2:] == ["control_socket_directory"] * 2

    phase = "PARKED"
    backend.state = phase
    integrations.retained_io = _io_for_graph(parked_graph, plan, running_old=False)
    drift = True
    invocations.clear()
    assert backend.restore_old(plan, held_lease) is False
    assert invocations == []


@pytest.mark.parametrize(
    "surviving_path,running_old,accepted",
    [
        ("control_socket_directory", True, True),
        ("parked", False, True),
        ("both", False, False),
        ("neither", False, False),
        ("parked_drift", False, False),
    ],
)
def test_interrupted_park_phase_staged_accepts_exact_one_historical_path_only(
    held_lease: cleanup.BocaJobLease,
    surviving_path: str,
    running_old: bool,
    accepted: bool,
) -> None:
    """A failed PARK must not strand its own compensation on a moved path."""
    bound = _bound()
    plan = bound.plan
    canonical = "control_socket_directory"
    parked = f"parked_control_socket_directory:{plan.attempt_id}"
    good = bound.custody.control_directory_inode_sha256
    seen: list[str] = []

    def read(path: str) -> str:
        seen.append(path)
        if (
            surviving_path == "both"
            or (surviving_path == "control_socket_directory" and path == canonical)
            or (surviving_path in ("parked", "parked_drift") and path == parked)
        ):
            return "a" * 64 if surviving_path == "parked_drift" else good
        missing = (
            ".boca-on-demand" if path == canonical else f".boca-on-demand-parked-{plan.attempt_id}"
        )
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", missing)

    source = (b"base", b"overlay", b"seccomp")
    pairs = PairSources(
        *source,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(source[0]).hexdigest(),
        overlay_sha=hashlib.sha256(source[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(source[2]).hexdigest(),
    )
    graph = physical.expected_transition_graph(
        plan, "STAGED", previous_observation=bound.original_pair_receipt
    )
    integrator = physical.PhysicalSuccessorIntegrations(
        plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=_io_for_graph(graph, plan, running_old=running_old),
        control_identity_reader=read,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        pairs, bound.retained, integrations=integrator, gate=None
    )
    integrator.bind_backend(backend)
    backend.state = "STAGED"
    backend.binding_park_started = True
    if accepted:
        assert integrator.retained_resources(plan, held_lease) == bound.retained
    else:
        with pytest.raises(physical.SuccessorPhysicalNoGo):
            integrator.retained_resources(plan, held_lease)
    if surviving_path != "neither":
        assert canonical in seen and parked in seen
