"""R252: one-shot FAILURE cleanup before the same journal terminal record.

No Docker, filesystem mutation or real Boca listener: the standalone physical
executor is separately tested and injected here only as a strict return type.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as repeatable
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure
from boca_socios import host_boca_upgrade_same_lease as same_lease
from test_host_boca_successor_stage_custody import _prepared


def _receipt(
    plan: transaction.PairCoordinates, *, restored: bool = False, committed: bool = False
) -> transaction.PairUpgradeReceipt:
    return transaction.PairUpgradeReceipt(
        plan.attempt_id,
        "NO_GO",
        "INDETERMINATE",
        restored,
        committed,
        None,
        None,
        "RETIRE_OLD" if committed else "STAGE",
    )


def _proof(
    plan: transaction.PairCoordinates, status: str = "ACCEPT"
) -> failure.DurableFailureCleanupReceipt:
    raw = b'{"synthetic_failure_receipt":"separately validated by official parser"}'
    return failure.DurableFailureCleanupReceipt(
        plan.attempt_id,
        status,
        raw,
        hashlib.sha256(raw).hexdigest(),
        "e" * 64,
    )


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, cleanup.BocaJobLease, list]:
    proof, durable = _prepared()
    plan = proof.inputs.plan
    lease = cleanup.BocaJobLease(plan.attempt_id, -1, os.getpid(), True)
    terminal: list[transaction.PairUpgradeReceipt] = []
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(durable, "attest_active_intent", lambda *_: None)
    monkeypatch.setattr(
        durable, "terminal", lambda _plan, receipt, _lease: terminal.append(receipt)
    )
    return proof, durable, lease, terminal


@pytest.mark.parametrize("restored", [True, False])
def test_precommit_failure_cleans_once_then_terminals_but_never_accepts_install(
    monkeypatch: pytest.MonkeyPatch,
    context: tuple[Any, Any, cleanup.BocaJobLease, list],
    restored: bool,
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    calls: list[dict[str, object]] = []
    parsing: list[tuple[str, bool]] = []

    def execute(*_args: object, **kwargs: object) -> failure.DurableFailureCleanupReceipt:
        calls.append(kwargs)
        return _proof(plan, status="ACCEPT" if restored else "NO_GO")

    def verify(_raw: bytes, run: str, *, require_install_success: bool = True) -> dict[str, str]:
        parsing.append((run, require_install_success))
        return {"outcome": "FAILURE", "status": "ACCEPT" if restored else "NO_GO"}

    monkeypatch.setattr(failure, "execute_durable_failure_cleanup", execute)
    monkeypatch.setattr(counted, "verify_cleanup_v2_receipt", verify)
    io = same_lease.ProductionRetainedResourceIO()
    sink = integration.OneShotFailureTerminalSink(plan, durable, retained_io=io)
    original = _receipt(plan, restored=restored)
    sink(plan, original, lease)
    assert terminal == [original]
    assert terminal[0].state == "NO_GO"
    assert terminal[0].cleanup == "INDETERMINATE"
    assert len(calls) == 1
    assert calls[0]["restored"] is restored
    assert calls[0]["receipt_dir"] is not None
    assert calls[0]["retained_io"] is (io if restored else None)
    assert parsing == [(plan.attempt_id, False)]
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        sink(plan, original, lease)


def test_recovered_old_pair_still_requires_durable_failure_cleanup_before_terminal(
    monkeypatch: pytest.MonkeyPatch,
    context: tuple[Any, Any, cleanup.BocaJobLease, list],
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    call_count = 0

    def execute(*_args: object, **kwargs: object) -> failure.DurableFailureCleanupReceipt:
        nonlocal call_count
        call_count += 1
        assert kwargs["restored"] is True
        assert type(kwargs["retained_io"]) is same_lease.ProductionRetainedResourceIO
        return _proof(plan)

    monkeypatch.setattr(failure, "execute_durable_failure_cleanup", execute)
    monkeypatch.setattr(
        counted,
        "verify_cleanup_v2_receipt",
        lambda *_args, **_kwargs: {"outcome": "FAILURE", "status": "ACCEPT"},
    )
    receipt = replace(_receipt(plan, restored=True), state="RECOVERED", cleanup="ACCEPT")
    sink = integration.OneShotFailureTerminalSink(
        plan, durable, retained_io=same_lease.ProductionRetainedResourceIO()
    )
    sink(plan, receipt, lease)
    assert call_count == 1
    assert terminal == [receipt]
    assert terminal[0].state == "RECOVERED"
    assert terminal[0].accepted is False


@pytest.mark.parametrize("committed,accepted", [(True, False), (True, True)])
def test_postcommit_or_success_never_invokes_failure_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    context: tuple[Any, Any, cleanup.BocaJobLease, list],
    committed: bool,
    accepted: bool,
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    monkeypatch.setattr(
        failure,
        "execute_durable_failure_cleanup",
        lambda *_args, **_kwargs: pytest.fail("postcommit failure cleanup is prohibited"),
    )
    sink = integration.OneShotFailureTerminalSink(plan, durable)
    original = _receipt(plan, committed=committed)
    if accepted:
        original = replace(original, state="ACCEPTED", cleanup="ACCEPT", failed_phase="NONE")
    if accepted:
        with pytest.raises(integration.SuccessorIntegrationNoGo):
            sink(plan, original, lease)
        assert terminal == []
    else:
        sink(plan, original, lease)
        assert terminal == [original]


@pytest.mark.parametrize(
    "mutation", ["missing_io", "wrong_type", "wrong_sha", "wrong_status", "wrong_outcome"]
)
def test_failure_proof_or_io_invalid_never_terminals_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
    context: tuple[Any, Any, cleanup.BocaJobLease, list],
    mutation: str,
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    calls = 0

    def execute(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if mutation == "wrong_type":
            return object()
        result = _proof(plan)
        return replace(result, sha256="0" * 64) if mutation == "wrong_sha" else result

    monkeypatch.setattr(failure, "execute_durable_failure_cleanup", execute)
    monkeypatch.setattr(
        counted,
        "verify_cleanup_v2_receipt",
        lambda *_args, **_kwargs: {
            "outcome": "SUCCESS" if mutation == "wrong_outcome" else "FAILURE",
            "status": "NO_GO" if mutation == "wrong_status" else "ACCEPT",
        },
    )
    sink = integration.OneShotFailureTerminalSink(
        plan,
        durable,
        retained_io=None if mutation == "missing_io" else same_lease.ProductionRetainedResourceIO(),
    )
    original = _receipt(plan, restored=True)
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        sink(plan, original, lease)
    assert terminal == []
    assert calls == (0 if mutation == "missing_io" else 1)
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        sink(plan, original, lease)
    assert calls == (0 if mutation == "missing_io" else 1)


def test_mismatched_plan_or_precommit_accept_is_refused_before_executor(
    monkeypatch: pytest.MonkeyPatch, context: tuple[Any, Any, cleanup.BocaJobLease, list]
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    monkeypatch.setattr(
        failure,
        "execute_durable_failure_cleanup",
        lambda *_args, **_kwargs: pytest.fail("invalid terminal must not mutate"),
    )
    wrong = replace(plan, old_controller_id="9" * 64)
    sink = integration.OneShotFailureTerminalSink(plan, durable)
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        sink(wrong, _receipt(plan), lease)
    assert terminal == []

    other = integration.OneShotFailureTerminalSink(plan, durable)
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        other(plan, replace(_receipt(plan), cleanup="ACCEPT"), lease)
    assert terminal == []


def test_unprimed_journal_refuses_before_failure_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    context: tuple[Any, Any, cleanup.BocaJobLease, list],
) -> None:
    proof, durable, lease, terminal = context
    plan = proof.inputs.plan
    monkeypatch.setattr(
        failure,
        "execute_durable_failure_cleanup",
        lambda *_args, **_kwargs: pytest.fail("cleanup before verified intent"),
    )
    monkeypatch.setattr(
        durable,
        "attest_active_intent",
        lambda current, held_lease: repeatable.SuccessorPairJournal.attest_active_intent(
            durable, current, held_lease
        ),
    )
    sink = integration.OneShotFailureTerminalSink(plan, durable)
    with pytest.raises(integration.SuccessorIntegrationNoGo):
        sink(plan, _receipt(plan), lease)
    assert terminal == []
