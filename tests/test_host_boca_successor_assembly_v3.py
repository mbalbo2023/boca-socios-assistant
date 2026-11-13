"""R253 same-lease actor graph, CODE_ONLY: zero Docker/lease effects."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_success_bridge_v2 as success_bridge
from boca_socios import host_boca_successor_assembly_v3 as assembly
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure
from boca_socios import host_boca_upgrade_same_lease as same_lease
from boca_socios import host_cutover_stage as stage

pytest_plugins = ("test_host_boca_success_cleanup_bridge_v2",)


def test_one_inert_graph_binds_stage_success_failure_and_journal_without_effects(
    monkeypatch: pytest.MonkeyPatch, frozen_proof: tuple[object, object]
) -> None:
    preflight, _unused_journal = frozen_proof
    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("Docker during assembly"))
    monkeypatch.setattr(
        cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("lease during assembly")
    )
    monkeypatch.setattr(stage, "_root_fd", lambda: pytest.fail("disk during assembly"))
    monkeypatch.setattr(
        failure,
        "execute_durable_failure_cleanup",
        lambda *_a, **_k: pytest.fail("FAILURE effect during assembly"),
    )
    monkeypatch.setattr(
        cleanup_runtime,
        "execute_durable_final_cleanup",
        lambda *_a, **_k: pytest.fail("SUCCESS effect during assembly"),
    )
    prepared = assembly.prepare_inert_same_lease(preflight)
    assert prepared.apply_authorized is False
    assert prepared.terminal_accept_authorized is False
    assert not hasattr(prepared, "execute")
    assert prepared.preflight is preflight
    assert prepared.plan is preflight.inputs.plan
    assert prepared.stage.journal is prepared.journal
    assert prepared.success.journal is prepared.journal
    assert prepared.failure.journal is prepared.journal
    assert prepared.stage.preflight is preflight
    assert prepared.success.plan is prepared.plan
    assert prepared.failure.plan is prepared.plan
    assert type(prepared.failure.retained_io) is same_lease.ProductionRetainedResourceIO
    assert prepared.success.backend.integrations is prepared.success.final_cleanup
    assert prepared.success.integrations.backend is prepared.success.backend
    assert prepared.success.backend.successor_postflight_gate is None
    assert type(prepared.success.backend).requires_persistent_receipt is False


def test_engine_refuses_inert_assembled_callbacks_before_lease(
    monkeypatch: pytest.MonkeyPatch, frozen_proof: tuple[object, object]
) -> None:
    preflight, _ = frozen_proof
    prepared = assembly.prepare_inert_same_lease(preflight)
    monkeypatch.setattr(
        cleanup,
        "protected_boca_job_lease",
        lambda *_: pytest.fail("unreviewed upgrade acquired lease"),
    )
    with pytest.raises(transaction.PairUpgradeError, match="protected terminal"):
        transaction.run_pair_upgrade(
            prepared.plan,
            backend=prepared.success.backend,
            terminal_preflight=prepared.stage.intent,
            commit_marker=prepared.journal.commit,
            terminal_sink=prepared.failure,
        )


@pytest.mark.parametrize("mutation", ["stage", "success", "failure", "plan"])
def test_foreign_component_or_plan_cannot_be_rebound_as_one_graph(
    frozen_proof: tuple[object, object], mutation: str
) -> None:
    preflight, _ = frozen_proof
    prepared = assembly.prepare_inert_same_lease(preflight)
    other = journal.SuccessorPairJournal(
        prepared.journal.release,
        prepared.journal.retained,
        prepared.journal.capture,
    )
    if mutation == "stage":
        kwargs: dict[str, object] = {
            "stage": integration.CurrentBaseOnlyStageCustody(preflight, other)
        }
    elif mutation == "success":
        from boca_socios import host_boca_success_bridge_v2 as success

        kwargs = {"success": success.prepare_success_cleanup(preflight, other)}
    elif mutation == "failure":
        kwargs = {
            "failure": integration.OneShotFailureTerminalSink(
                prepared.plan,
                other,
                retained_io=same_lease.ProductionRetainedResourceIO(),
            )
        }
    else:
        kwargs = {"plan": replace(prepared.plan, old_controller_id="9" * 64)}
    with pytest.raises(assembly.SuccessorAssemblyNoGo):
        replace(prepared, **kwargs)


def test_invalid_preflight_is_not_a_lease_or_docker_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("Docker on invalid input"))
    monkeypatch.setattr(
        cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("lease on invalid input")
    )
    for input_value in (None, object(), "456"):
        with pytest.raises(assembly.SuccessorAssemblyNoGo):
            assembly.prepare_inert_same_lease(input_value)


@pytest.mark.parametrize("mutation", ["capture_reader", "cleanup_reader", "lease_verifier"])
def test_rebound_graph_rejects_modified_physical_reader_defaults(
    frozen_proof: tuple[object, object], mutation: str
) -> None:
    preflight, _ = frozen_proof
    prepared = assembly.prepare_inert_same_lease(preflight)
    if mutation == "capture_reader":
        capture = replace(prepared.journal.capture, pair_reader=lambda _attempt: b"fake")
        other = journal.SuccessorPairJournal(
            prepared.journal.release, prepared.journal.retained, capture
        )
        stage_adapter = integration.CurrentBaseOnlyStageCustody(preflight, other)
        success_adapter = replace(prepared.success, journal=other)
        failure_adapter = integration.OneShotFailureTerminalSink(
            prepared.plan, other, retained_io=same_lease.ProductionRetainedResourceIO()
        )
        candidate = {
            "journal": other,
            "stage": stage_adapter,
            "success": success_adapter,
            "failure": failure_adapter,
        }
    else:
        if mutation == "cleanup_reader":
            prepared.success.final_cleanup._read_coordinates = lambda *_: None
        else:
            prepared.success.final_cleanup._verify_lease = lambda *_: None
        candidate = {
            "success": success_bridge.BoundSuccessCleanup(
                prepared.plan,
                prepared.journal,
                prepared.success.integrations,
                prepared.success.final_cleanup,
                prepared.success.backend,
            )
        }
    with pytest.raises(assembly.SuccessorAssemblyNoGo):
        replace(prepared, **candidate)
