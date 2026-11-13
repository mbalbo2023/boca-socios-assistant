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
from boca_socios import host_on_demand_service as service
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
    duplicate_root = False

    def control(name: str) -> str:
        reads.append(name)
        if name == f"parked_control_socket_directory:{plan.attempt_id}":
            if (
                active_phase in ("NEW", "ATTESTED", "STAGED", "RETIRED", "RESTORED")
                and not duplicate_root
            ):
                raise FileNotFoundError(
                    errno.ENOENT,
                    "No such file or directory",
                    f".boca-on-demand-parked-{plan.attempt_id}",
                )
            return old_inode
        if name == "control_socket_directory":
            if active_phase in ("PARKED", "WORKER") and not duplicate_root:
                raise FileNotFoundError(
                    errno.ENOENT, "No such file or directory", ".boca-on-demand"
                )
            return (
                old_inode
                if active_phase in ("NEW", "ATTESTED", "STAGED", "RESTORED")
                else new_inode
            )
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
        "ATTESTED",
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
            graph, plan, running_old=active_phase in ("NEW", "ATTESTED", "STAGED")
        )
        reads.clear()
        assert integrator.retained_resources(plan, held_lease) == bound.retained
        assert sorted(set(reads)) == sorted(
            ["control_socket_directory", f"parked_control_socket_directory:{plan.attempt_id}"]
        )
        assert len(reads) == 4
        if active_phase in ("NEW", "ATTESTED", "STAGED", "PARKED", "WORKER", "RETIRED"):
            # A second control root in a phase that requires absence must
            # not be treated as harmless even if its inode has a valid hash.
            duplicate_root = True
            with pytest.raises(physical.SuccessorPhysicalNoGo):
                integrator.retained_resources(plan, held_lease)
            duplicate_root = False


def test_recovery_must_return_to_original_canonical_control_path(
    held_lease: cleanup.BocaJobLease,
) -> None:
    bound = _bound()
    plan = bound.plan
    graph = physical.expected_transition_graph(
        plan, "RESTORED", previous_observation=bound.original_pair_receipt
    )
    asks: list[str] = []
    unexpected_parked = False

    def canonical(name: str) -> str:
        asks.append(name)
        if name == f"parked_control_socket_directory:{plan.attempt_id}" and not unexpected_parked:
            raise FileNotFoundError(
                errno.ENOENT,
                "No such file or directory",
                f".boca-on-demand-parked-{plan.attempt_id}",
            )
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
    assert (
        asks
        == ["control_socket_directory"] * 2
        + [f"parked_control_socket_directory:{plan.attempt_id}"] * 2
    )
    unexpected_parked = True
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        integrator.retained_resources(plan, held_lease)


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
            if phase == "RESTORED":
                raise FileNotFoundError(
                    errno.ENOENT,
                    "No such file or directory",
                    f".boca-on-demand-parked-{plan.attempt_id}",
                )
            return "a" * 64 if drift else bound.custody.control_directory_inode_sha256
        if name == "control_socket_directory" and phase == "RESTORED":
            return bound.custody.control_directory_inode_sha256
        if name == "control_socket_directory" and phase == "PARKED":
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", ".boca-on-demand")
        raise AssertionError("wrong selector during compensation")

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
    assert calls[-2:] == [f"parked_control_socket_directory:{plan.attempt_id}"] * 2

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
        ("canonical_socket_missing", False, False),
        ("parked_socket_missing", True, False),
        ("absent_flaps", False, False),
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
    canonical_reads = 0

    def read(path: str) -> str:
        nonlocal canonical_reads
        seen.append(path)
        if path == canonical:
            canonical_reads += 1
        if surviving_path == "absent_flaps":
            if path == canonical and canonical_reads <= 2:
                raise FileNotFoundError(
                    errno.ENOENT, "No such file or directory", ".boca-on-demand"
                )
            return good
        if surviving_path == "canonical_socket_missing" and path == canonical:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "socket")
        if surviving_path == "parked_socket_missing" and path == parked:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "socket")
        if (
            surviving_path == "both"
            or (surviving_path == "canonical_socket_missing" and path == parked)
            or (surviving_path == "parked_socket_missing" and path == canonical)
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
    if surviving_path not in ("neither", "absent_flaps", "canonical_socket_missing"):
        assert canonical in seen and parked in seen


@pytest.mark.parametrize(
    "root_state,prepare_started,accepted",
    [
        ("marker_only", True, True),
        ("empty_socket", True, True),
        ("marker_only", False, False),
        ("foreign_marker", True, False),
        ("unexpected_binding", True, False),
        ("socket_payload", True, False),
        ("socket_mode", True, False),
        ("socket_appears", True, False),
        ("known_controller", True, False),
    ],
)
def test_worker_interrupted_control_prepare_requires_exact_new_attempt_root(
    held_lease: cleanup.BocaJobLease,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    root_state: str,
    prepare_started: bool,
    accepted: bool,
) -> None:
    """Compensation can remove a proven partial root, never a foreign one."""
    bound = _bound()
    plan = bound.plan
    home = tmp_path / "boca-deploy"
    home.mkdir(mode=0o700)
    root = home / ".boca-on-demand"
    root.mkdir(mode=0o700)
    marker = root / "attempt"
    marker.write_text(
        ("11111111111" if root_state == "foreign_marker" else plan.attempt_id) + "\n",
        encoding="ascii",
    )
    marker.chmod(0o600)
    if root_state in ("empty_socket", "socket_payload", "socket_mode"):
        socket = root / "socket"
        socket.mkdir(mode=0o711)
        socket.chmod(0o755 if root_state == "socket_mode" else 0o711)
        if root_state == "socket_payload":
            (socket / "unexpected.sock").touch()
    if root_state == "unexpected_binding":
        (root / "binding.json").touch()
    monkeypatch.setattr(service, "_home", lambda: home)
    if root_state == "socket_appears":
        real_owned = service._owned
        calls = 0

        def mutate_between_observations(current: Path, attempt: str) -> Path:
            nonlocal calls
            owned = real_owned(current, attempt)
            calls += 1
            if calls == 2:
                folder = owned / "socket"
                folder.mkdir(mode=0o711)
                folder.chmod(0o711)
            return owned

        monkeypatch.setattr(service, "_owned", mutate_between_observations)

    def control(name: str) -> str:
        if name == f"parked_control_socket_directory:{plan.attempt_id}":
            return bound.custody.control_directory_inode_sha256
        if name == "control_socket_directory":
            if (root / "socket").is_dir():
                return "a" * 64
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "socket")
        raise AssertionError("unexpected selector")

    raw = (b"base", b"overlay", b"seccomp")
    sources = PairSources(
        *raw,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(raw[0]).hexdigest(),
        overlay_sha=hashlib.sha256(raw[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(raw[2]).hexdigest(),
    )
    graph = physical.expected_transition_graph(
        plan, "WORKER", worker_id="e" * 64, previous_observation=bound.original_pair_receipt
    )
    integrator = physical.PhysicalSuccessorIntegrations(
        plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=_io_for_graph(graph, plan, running_old=False),
        control_identity_reader=control,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        sources, bound.retained, integrations=integrator, gate=None
    )
    integrator.bind_backend(backend)
    backend.state = "WORKER"
    backend.worker_id = "e" * 64
    backend.control_prepare_started = prepare_started
    if root_state == "known_controller":
        # The source graph cannot safely claim 3 containers after a known
        # fourth CID was created but the actor did not reach CONTROLLER.
        backend.controller_id = "f" * 64
    if accepted:
        assert integrator.retained_resources(plan, held_lease) == bound.retained
    else:
        with pytest.raises(physical.SuccessorPhysicalNoGo):
            integrator.retained_resources(plan, held_lease)


def test_controller_marks_preparation_before_first_control_effect(
    held_lease: cleanup.BocaJobLease, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boca_socios import host_boca_pair_stage as staging
    from boca_socios import host_first_deploy as host

    bound = _bound()
    actor = historical.RootlessPairUpgradeBackend(
        PairSources(
            b"base",
            b"overlay",
            b"seccomp",
            "f" * 64,
            hashlib.sha256(b"base").hexdigest(),
            hashlib.sha256(b"overlay").hexdigest(),
            hashlib.sha256(b"seccomp").hexdigest(),
        )
    )
    actor.state = "WORKER"
    actor.worker_id = "e" * 64
    monkeypatch.setattr(actor, "_guard", lambda *_: None)
    monkeypatch.setattr(staging, "verify", lambda *_: None)
    monkeypatch.setattr(host, "_browser_port_free", lambda **_kwargs: None)
    seen: list[bool] = []

    def interrupted_prepare(*_args: object) -> Path:
        seen.append(getattr(actor, "control_prepare_started", False))
        raise RuntimeError("simulated control preparation interruption")

    monkeypatch.setattr(service, "prepare_control_directory", interrupted_prepare)
    with pytest.raises(RuntimeError, match="control preparation interruption"):
        actor.create_controller(bound.plan, "e" * 64, held_lease)
    assert seen == [True]
