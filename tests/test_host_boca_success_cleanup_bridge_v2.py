"""R252 CODE_ONLY success cleanup composition; never touches Docker or a lease."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_success_bridge_v2 as bridge
from boca_socios import host_boca_successor_integrations as integrator
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_successor_runtime as successor
from test_host_boca_successor_integrations import _inputs_with_proofs
from test_host_boca_upgrade_postflight import _expected, _technical_capture


@pytest.fixture
def frozen_proof() -> tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal]:
    bound = integrator.verify_runner_bound_host_inputs(**_inputs_with_proofs(step=2))
    root = Path(__file__).resolve().parents[1]
    base, overlay, seccomp = (
        (root / name).read_bytes()
        for name in (
            "compose.beta.yaml",
            "compose.beta.browser.yaml",
            "docker/seccomp_profile.json",
        )
    )
    preflight = cli.BoundSuccessorPreflight(
        bound,
        base,
        overlay,
        seccomp,
        *(hashlib.sha256(data).hexdigest() for data in (base, overlay, seccomp)),
    )
    capture = physical.SuccessorCurrentPairCapture(
        historical_custody=bound.custody,
        current_pair_observation=bound.original_pair_receipt,
    )
    durable = journal.SuccessorPairJournal(bound.release, bound.custody.resources, capture)
    return preflight, durable


def test_success_cleanup_composition_uses_one_exact_physical_adapter_and_real_reader(
    monkeypatch: pytest.MonkeyPatch,
    frozen_proof: tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal],
) -> None:
    preflight, durable = frozen_proof
    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("Docker in assembly"))
    monkeypatch.setattr(
        cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("lease in assembly")
    )
    assembled = bridge.prepare_success_cleanup(preflight, durable)
    assert assembled.apply_authorized is False
    assert assembled.plan is preflight.inputs.plan
    assert assembled.journal is durable
    assert assembled.integrations.backend is assembled.backend
    assert assembled.backend.integrations is assembled.final_cleanup
    assert assembled.final_cleanup._delegate is assembled.integrations
    assert assembled.final_cleanup._verify_lease is cleanup.verify_protected_boca_job_lease
    assert (
        type(assembled.final_cleanup._read_coordinates)
        is successor.ProductionFinalCleanupCoordinatesReader
    )
    assert assembled.backend.successor_postflight_gate is None
    assert type(assembled.backend).requires_persistent_receipt is False


@pytest.mark.parametrize(
    "mutation", ("release", "retained", "capture", "pair", "reader", "wrong_stage")
)
def test_success_cleanup_refuses_nonmatching_or_injected_provenance(
    frozen_proof: tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal],
    mutation: str,
) -> None:
    preflight, durable = frozen_proof
    if mutation == "release":
        durable.release = replace(durable.release, release_run_id="456")
    elif mutation == "retained":
        durable.retained = replace(durable.retained, egress_id="a" * 64)
    elif mutation == "capture":
        durable.capture = lambda _plan, _lease: None
    elif mutation == "pair":
        capture = durable.capture
        assert type(capture) is physical.SuccessorCurrentPairCapture
        durable.capture = replace(capture, current_pair_observation=b"fake")
    elif mutation == "reader":
        capture = durable.capture
        assert type(capture) is physical.SuccessorCurrentPairCapture
        durable.capture = replace(capture, pair_reader=lambda _run: b"fake")
    else:
        with pytest.raises(cli.SuccessorPreflightIneligible):
            replace(preflight, base_sha="e" * 64)
        return
    with pytest.raises(bridge.SuccessCleanupBridgeNoGo):
        bridge.prepare_success_cleanup(preflight, durable)


def test_exact_bridge_cannot_bind_an_unrelated_physical_adapter(
    frozen_proof: tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal],
) -> None:
    preflight, durable = frozen_proof
    assembled = bridge.prepare_success_cleanup(preflight, durable)
    other = physical.PhysicalSuccessorIntegrations(
        preflight.inputs.plan,
        preflight.inputs.release,
        preflight.inputs.custody,
        preflight.inputs.original_pair_receipt,
    )
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        other.bind_backend(assembled.backend)
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        assembled.integrations.bind_backend(assembled.backend)


def test_success_composition_does_not_relax_engine_type_guard(
    frozen_proof: tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal],
) -> None:
    preflight, durable = frozen_proof
    assembled = bridge.prepare_success_cleanup(preflight, durable)
    with pytest.raises(transaction.PairUpgradeError, match="protected terminal"):
        transaction.run_pair_upgrade(
            assembled.plan,
            backend=assembled.backend,
            terminal_preflight=assembled.journal.intent,
            commit_marker=assembled.journal.commit,
            terminal_sink=assembled.journal.terminal,
        )
    assert assembled.backend.state == "NEW"


def test_technical_success_evidence_is_canonical_but_cannot_authorize_beta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    raw, _checks = _technical_capture()
    proof = cleanup_runtime.DurableFinalCleanupReceipt(
        expected.plan.attempt_id,
        "ACCEPT",
        expected.cleanup_receipt,
        hashlib.sha256(expected.cleanup_receipt).hexdigest(),
        "f" * 64,
    )
    original = successor.OneShotFinalCleanupBridge(
        None,
        read_cleanup_coordinates=None,
        verify_lease=None,  # type: ignore[arg-type]
    )
    called: list[tuple[transaction.PairCoordinates, cleanup.BocaJobLease]] = []

    def completed(
        plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> cleanup_runtime.DurableFinalCleanupReceipt:
        called.append((plan, lease))
        return proof

    monkeypatch.setattr(original, "completed_final_cleanup", completed)
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    lease_checks: list[tuple[cleanup.BocaJobLease, str]] = []
    monkeypatch.setattr(
        cleanup,
        "verify_protected_boca_job_lease",
        lambda held, attempt: lease_checks.append((held, attempt)),
    )
    result = bridge.verify_technical_completion(expected.plan, lease, original, expected, raw)
    assert called == [(expected.plan, lease)]
    assert result.cleanup_receipt is proof
    assert result.technical_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.apply_authorized is False
    assert result.terminal_accept_authorized is False
    assert result.beta_deploy == "NO_GO"
    assert lease_checks == [(lease, expected.plan.attempt_id)] * 2


@pytest.mark.parametrize("mutation", ("raw", "proof", "expected", "foreign_plan", "missing_lease"))
def test_technical_completion_never_promotes_invalid_or_foreign_evidence(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    expected = _expected()
    raw, _ = _technical_capture()
    proof = cleanup_runtime.DurableFinalCleanupReceipt(
        expected.plan.attempt_id,
        "ACCEPT",
        expected.cleanup_receipt,
        hashlib.sha256(expected.cleanup_receipt).hexdigest(),
        "a" * 64,
    )
    original = successor.OneShotFinalCleanupBridge(
        None,
        read_cleanup_coordinates=None,
        verify_lease=None,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(original, "completed_final_cleanup", lambda *_: proof)
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    actual_plan = expected.plan
    if mutation == "raw":
        raw = raw.replace(b'"beta_deploy":"NO_GO"', b'"beta_deploy":"GO"')
    elif mutation == "proof":
        monkeypatch.setattr(
            original, "completed_final_cleanup", lambda *_: replace(proof, sha256="f" * 64)
        )
    elif mutation == "expected":
        expected = replace(expected, site_url_fingerprint="0" * 64)
    elif mutation == "foreign_plan":
        actual_plan = replace(expected.plan, new_source_sha="1" * 40)
    else:
        lease = None  # type: ignore[assignment]
    with pytest.raises(bridge.SuccessCleanupBridgeNoGo):
        bridge.verify_technical_completion(actual_plan, lease, original, expected, raw)


def test_technical_completion_refuses_lease_lost_after_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    raw, _ = _technical_capture()
    original = successor.OneShotFinalCleanupBridge(
        None,
        read_cleanup_coordinates=None,
        verify_lease=None,  # type: ignore[arg-type]
    )
    receipt = cleanup_runtime.DurableFinalCleanupReceipt(
        expected.plan.attempt_id,
        "ACCEPT",
        expected.cleanup_receipt,
        hashlib.sha256(expected.cleanup_receipt).hexdigest(),
        "f" * 64,
    )
    monkeypatch.setattr(original, "completed_final_cleanup", lambda *_: receipt)
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    called = 0

    def verify(_lease: cleanup.BocaJobLease, _attempt: str) -> None:
        nonlocal called
        called += 1
        if called == 2:
            raise OSError("lease no longer authentic")

    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", verify)
    with pytest.raises(bridge.SuccessCleanupBridgeNoGo):
        bridge.verify_technical_completion(expected.plan, lease, original, expected, raw)
    assert called == 2
