"""Offline 1102 successor graph and restoration; no Docker or host actions."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_current_retained as current_resources
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure
from boca_socios.host_on_demand_lifecycle import PanelStatus
from test_host_boca_pair_upgrade_reusable import _sources
from test_host_boca_successor_physical_v2 import _io_for_graph
from test_host_boca_upgrade_adapters import EGRESS, IPC, SITE
from test_r294_current_retained import CONTROL, current_pair, installation
from test_r294_promotion_runner import NEW_APPLY, bound_inputs


@pytest.fixture
def held_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    directory = tmp_path / "lease"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", directory)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    with cleanup.protected_boca_job_lease(NEW_APPLY) as lease:
        yield lease


def retained_io(bound, graph, phase: str):
    io = _io_for_graph(graph, bound.plan, running_old=phase in ("NEW", "RESTORED"))
    pins = bound.custody.resources
    io.identities[IPC] = pins.ipc_inode_sha256
    io.identities[SITE] = pins.site_inode_sha256
    io.value = replace(
        io.value,
        networks=tuple(
            replace(item, ident=pins.egress_id) if item.name == EGRESS else item
            for item in io.value.networks
        ),
    )
    io.worker_state = lambda cid: {
        "Status": "exited" if cid == bound.plan.old_worker_id else "created",
        "Running": False,
        "Pid": 0,
        "ExitCode": 0,
    }
    return io


@pytest.mark.parametrize(
    "phase", ("NEW", "PARKED", "WORKER", "CONTROLLER", "BOUND", "RETIRED", "RESTORED")
)
def test_current_stop_policy_survives_each_successor_phase(
    tmp_path: Path, held_lease: cleanup.BocaJobLease, phase: str
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    graph = physical.expected_transition_graph(
        bound.plan,
        phase,
        worker_id="e" * 64 if phase in ("WORKER", "CONTROLLER", "BOUND", "RETIRED") else None,
        controller_id="f" * 64 if phase in ("CONTROLLER", "BOUND", "RETIRED") else None,
        previous_observation=bound.original_pair_receipt,
        current_retained=bound.custody.current_receipt,
    )
    io = retained_io(bound, graph, phase)
    assert (
        physical.observe_transition_resources(
            bound.plan, bound.custody, held_lease, graph=graph, retained_io=io
        )
        == bound.custody.resources
    )


def test_successor_candidate_never_inherits_old_worker_stop_exception(
    tmp_path: Path, held_lease: cleanup.BocaJobLease
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    graph = physical.expected_transition_graph(
        bound.plan,
        "WORKER",
        worker_id="e" * 64,
        previous_observation=bound.original_pair_receipt,
        current_retained=bound.custody.current_receipt,
    )
    io = retained_io(bound, graph, "WORKER")
    io.worker_state = lambda _cid: {"Status": "exited", "Running": False, "Pid": 0, "ExitCode": 0}
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        physical.observe_transition_resources(
            bound.plan, bound.custody, held_lease, graph=graph, retained_io=io
        )


def test_unreceipted_worker_stop_stays_no_go(
    tmp_path: Path, held_lease: cleanup.BocaJobLease
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    graph = physical.expected_transition_graph(
        bound.plan,
        "NEW",
        previous_observation=bound.original_pair_receipt,
        current_retained=bound.custody.current_receipt,
    )
    io = retained_io(bound, graph, "NEW")
    with pytest.raises(adapters.EvidenceNoGo):
        adapters.observe_retained(
            bound.custody.resources,
            replace(graph, current_retained=None),
            bound.plan.attempt_id,
            held_lease,
            io=io,
        )


def test_current_capture_reproves_actual_binding_stop_and_current_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held_lease: cleanup.BocaJobLease
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    status = PanelStatus(
        "00000000-0000-4000-8000-000000000001", "stop", "APPLIED", "NONE", None, None, None
    )
    monkeypatch.setattr(current_resources, "read_panel_status", lambda _installed: status)
    graph = physical.expected_transition_graph(
        bound.plan,
        "NEW",
        previous_observation=bound.original_pair_receipt,
        current_retained=bound.custody.current_receipt,
    )
    capture = physical.SuccessorCurrentPairCapture(
        bound.custody,
        bound.original_pair_receipt,
        retained_io=retained_io(bound, graph, "NEW"),
        pair_reader=lambda run: current_pair(run=run, stopped=True),
        binding_reader=lambda _lease: installation(),
        control_identity_reader=lambda _name: CONTROL,
    )
    assert capture(bound.plan, held_lease).control_inode_sha256 == CONTROL
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        replace(capture, control_identity_reader=lambda _name: "7" * 64)(bound.plan, held_lease)
    status = replace(status, operation_id="00000000-0000-4000-8000-000000000002")
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        capture(bound.plan, held_lease)


@pytest.mark.parametrize("parked", (False, True))
def test_actor_accepts_only_receipted_old_exited_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parked: bool
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    installed = installation()

    def old_record(_plan, _cid, *, role, name, running):
        return {
            "State": {"Status": "exited", "Running": running, "Pid": 0, "ExitCode": 0},
            "HostConfig": {
                "RestartPolicy": {
                    "Name": "unless-stopped" if role == "controller" and not parked else "no",
                    "MaximumRetryCount": 0,
                }
            },
            "Config": {
                "Labels": {
                    "com.docker.compose.config-hash": (
                        installed.pair.controller_config_hash
                        if role == "controller"
                        else installed.pair.worker_config_hash
                    )
                }
            },
        }

    monkeypatch.setattr(reusable.historical, "_full_old_record", old_record)
    actor = reusable.ReusablePairUpgradeBackend(
        _sources(), bound.retained, current_retained=bound.custody.current_receipt
    )
    actor.old = installed
    actor._old_exact(bound.plan, parked=parked)
    default = reusable.ReusablePairUpgradeBackend(_sources(), bound.retained)
    default.old = installed
    with pytest.raises(ValueError):
        default._old_exact(bound.plan, parked=parked)


def test_restored_old_worker_needs_same_current_receipt_before_failure_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held_lease: cleanup.BocaJobLease
) -> None:
    bound = bound_inputs(tmp_path, stopped=True)
    installed = installation()
    graph = physical.expected_transition_graph(
        bound.plan,
        "RESTORED",
        previous_observation=bound.original_pair_receipt,
        current_retained=bound.custody.current_receipt,
    )
    io = retained_io(bound, graph, "RESTORED")
    io.value = replace(
        io.value,
        containers=tuple(
            replace(
                item,
                labels=tuple(
                    sorted(
                        (
                            *item.labels,
                            (
                                "com.docker.compose.config-hash",
                                installed.pair.controller_config_hash
                                if item.ident == bound.plan.old_controller_id
                                else installed.pair.worker_config_hash,
                            ),
                        )
                    )
                ),
            )
            for item in io.value.containers
        ),
    )
    monkeypatch.setattr(failure, "_probe_r108", lambda *_: io.value)
    monkeypatch.setattr(failure.service, "read_installed_binding", lambda _lease: installed)
    monkeypatch.setattr(
        current_resources,
        "read_panel_status",
        lambda _installed: PanelStatus(
            "00000000-0000-4000-8000-000000000001", "stop", "APPLIED", "NONE", None, None, None
        ),
    )
    with pytest.raises(ValueError):
        failure._restored_snapshot(bound.plan, held_lease, bound.custody.resources, io)
    assert (
        failure._restored_snapshot(
            bound.plan,
            held_lease,
            bound.custody.resources,
            io,
            current_retained=bound.custody.current_receipt,
        )
        == io.value
    )
    monkeypatch.setattr(
        failure.service,
        "read_installed_binding",
        lambda _lease: replace(installed, database_path=Path("/data/boca.sqlite3")),
    )
    with pytest.raises(ValueError):
        failure._restored_snapshot(
            bound.plan,
            held_lease,
            bound.custody.resources,
            io,
            current_retained=bound.custody.current_receipt,
        )
