"""Fail-closed successor finalization: no live Docker, network or releases."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios.host_boca_upgrade_cleanup_runtime import DurableFinalCleanupReceipt
from test_host_boca_pair_upgrade_reusable import _pins, _sources
from test_host_boca_upgrade_postflight import _expected, _snapshot


def _receipt() -> DurableFinalCleanupReceipt:
    raw = _expected().cleanup_receipt
    return DurableFinalCleanupReceipt(
        attempt_id="98765",
        status="ACCEPT",
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        intent_sha256="a" * 64,
    )


def _gate(tmp_path: Path, *, read_snapshot: Any = None) -> successor.SuccessorPostflightGate:
    expected = _expected()

    def open_dir() -> int:
        return os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    return successor.SuccessorPostflightGate(
        release=expected.release,
        retained=expected.retained,
        storage_before=expected.storage_before,
        site_url_fingerprint=expected.site_url_fingerprint,
        controller_image_id=expected.controller_image_id,
        worker_image_id=expected.worker_image_id,
        read_snapshot=read_snapshot if read_snapshot is not None else lambda _: _snapshot(),
        verify_lease=lambda lease, attempt: _assert_lease(lease, attempt),
        open_receipt_directory=open_dir,
    )


def _assert_lease(lease: cleanup.BocaJobLease, attempt: str) -> None:
    assert lease.attempt_id == attempt == "98765"
    assert lease.active


def _lease() -> cleanup.BocaJobLease:
    return cleanup.BocaJobLease("98765", -1, os.getpid(), True)


def _cleanup_coordinates(tmp_path: Path) -> successor.FinalCleanupCoordinates:
    return successor.FinalCleanupCoordinates(
        controller_id="c" * 64,
        worker_id="d" * 64,
        controller_image_id="sha256:" + "1" * 64,
        worker_image_id="sha256:" + "2" * 64,
        receipt_dir=tmp_path,
        historical_retained=cleanup.HistoricalRetainedImageProof(
            cleanup.HISTORICAL_RETIRE_TARGET,
            cleanup.HISTORICAL_RETIRE_DIGEST,
            cleanup.HISTORICAL_RETIRE_REVISION,
        ),
    )


def test_postflight_gate_rejects_unwired_capture_without_making_accepted_receipt(
    tmp_path: Path,
) -> None:
    expected = _expected()
    gate = successor.SuccessorPostflightGate(
        release=expected.release,
        retained=expected.retained,
        storage_before=expected.storage_before,
        site_url_fingerprint=expected.site_url_fingerprint,
        controller_image_id=expected.controller_image_id,
        worker_image_id=expected.worker_image_id,
        read_snapshot=None,
        verify_lease=None,
        open_receipt_directory=None,
    )
    with pytest.raises(successor.SuccessorFinalizationNoGo, match="NO_GO"):
        gate.attest(_expected().plan, _lease(), _receipt(), "c" * 64, "d" * 64)
    assert list(tmp_path.iterdir()) == []


def test_postflight_gate_double_reads_and_writes_exclusive_canonical_receipt(
    tmp_path: Path,
) -> None:
    reads: list[int] = []

    def snapshot(lease: cleanup.BocaJobLease) -> Any:
        reads.append(lease.fd)
        return _snapshot()

    gate = _gate(tmp_path, read_snapshot=snapshot)
    receipt = gate.attest(_expected().plan, _lease(), _receipt(), "c" * 64, "d" * 64)
    assert receipt.startswith(b"BOCA_PAIR_POSTFLIGHT ")
    assert len(reads) == 2
    persisted = list(tmp_path.iterdir())
    assert len(persisted) == 1
    assert persisted[0].read_bytes() == receipt
    assert persisted[0].stat().st_mode & 0o777 == 0o600


def test_postflight_gate_rejects_cleanup_receipt_forgery_and_wrong_attempt(tmp_path: Path) -> None:
    proof = _receipt()
    for forged in (
        DurableFinalCleanupReceipt(
            "98766", proof.status, proof.raw, proof.sha256, proof.intent_sha256
        ),
        DurableFinalCleanupReceipt(
            proof.attempt_id, proof.status, proof.raw, "0" * 64, proof.intent_sha256
        ),
        DurableFinalCleanupReceipt(
            proof.attempt_id, "NO_GO", proof.raw, proof.sha256, proof.intent_sha256
        ),
    ):
        with pytest.raises(successor.SuccessorFinalizationNoGo):
            _gate(tmp_path).attest(_expected().plan, _lease(), forged, "c" * 64, "d" * 64)
    assert list(tmp_path.iterdir()) == []


def test_postflight_gate_rejects_changed_second_same_lease_snapshot(tmp_path: Path) -> None:
    from dataclasses import replace

    reads = iter((_snapshot(), replace(_snapshot(), rootless_uid=0)))
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        _gate(tmp_path, read_snapshot=lambda _: next(reads)).attest(
            _expected().plan, _lease(), _receipt(), "c" * 64, "d" * 64
        )
    assert list(tmp_path.iterdir()) == []


def test_postflight_gate_fails_after_effect_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boca_socios import host_cutover_stage as stage

    original = stage._create_exclusive
    invocations = 0

    def ambiguous(fd: int, name: str, raw: bytes) -> None:
        nonlocal invocations
        invocations += 1
        original(fd, name, raw)
        raise OSError("post-write transport uncertainty")

    monkeypatch.setattr(stage, "_create_exclusive", ambiguous)
    gate = _gate(tmp_path)
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        gate.attest(_expected().plan, _lease(), _receipt(), "c" * 64, "d" * 64)
    assert len(list(tmp_path.iterdir())) == 1
    monkeypatch.setattr(stage, "_create_exclusive", original)
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        gate.attest(_expected().plan, _lease(), _receipt(), "c" * 64, "d" * 64)
    assert invocations == 1
    assert len(list(tmp_path.iterdir())) == 1


def test_backend_never_returns_accept_without_typed_cleanup_and_postflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Integrations:
        def __init__(self) -> None:
            self.cleaned = 0

        def completed_final_cleanup(self, plan: Any, lease: Any) -> Any:
            assert plan.attempt_id == lease.attempt_id == "98765"
            return _receipt()

    integrations = Integrations()
    backend = successor.PostflightGatedSuccessorBackend(
        _sources(), _pins(), integrations, gate=None
    )
    assert type(backend).requires_persistent_receipt is False
    # Unwired means no inherited cleanup or effectful finalizer may execute.
    monkeypatch.setattr(
        reusable.ReusablePairUpgradeBackend,
        "finalize",
        lambda *_args, **_kwargs: pytest.fail("unwired backend invoked cleanup"),
    )
    assert (
        backend.finalize(
            _expected().plan,
            commit_started=True,
            controller_id="c" * 64,
            worker_id="d" * 64,
            lease=_lease(),
        )
        == "NO_GO"
    )


def test_backend_success_is_gated_within_finalize_and_is_one_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boca_socios import host_boca_pair_upgrade as transaction

    class Delegate:
        def verify_release(self, *_args: Any) -> None: ...

        def retained_resources(self, *_args: Any) -> Any:
            return _pins()

        def final_cleanup(self, *_args: Any) -> str:
            pytest.fail("duplicate bare-string final cleanup")

    effects: list[str] = []

    def execute_final_cleanup(
        _plan: Any, _lease: Any, **_kwargs: Any
    ) -> DurableFinalCleanupReceipt:
        effects.append("cleanup_v2")
        return _receipt()

    monkeypatch.setattr(
        successor.cleanup_runtime, "execute_durable_final_cleanup", execute_final_cleanup
    )
    integrations = successor.OneShotFinalCleanupBridge(
        Delegate(),
        read_cleanup_coordinates=lambda *_: _cleanup_coordinates(tmp_path),
        verify_lease=_assert_lease,
    )

    backend = successor.PostflightGatedSuccessorBackend(
        _sources(), _pins(), integrations, gate=_gate(tmp_path)
    )
    base_calls = 0

    def base_finalize(*_args: Any, **_kwargs: Any) -> str:
        nonlocal base_calls
        base_calls += 1
        return integrations.final_cleanup(_args[1], _kwargs["lease"])

    monkeypatch.setattr(reusable.ReusablePairUpgradeBackend, "finalize", base_finalize)
    args = dict(
        plan=_expected().plan,
        commit_started=True,
        controller_id="c" * 64,
        worker_id="d" * 64,
        lease=_lease(),
    )
    assert backend.finalize(**args) == "ACCEPT"
    assert backend.finalize(**args) == "INDETERMINATE"
    assert base_calls == 1
    assert effects == ["cleanup_v2"]
    with pytest.raises(transaction.PairUpgradeError):
        transaction.run_pair_upgrade(
            _expected().plan,
            backend=backend,
            terminal_preflight=lambda *_: pytest.fail("intent written"),
            commit_marker=lambda *_: pytest.fail("committed"),
            terminal_sink=lambda *_: pytest.fail("terminal"),
        )


def test_cleanup_bridge_never_reads_pseudoproof_or_repeats_after_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Delegate:
        def verify_release(self, *_args: Any) -> None: ...

        def retained_resources(self, *_args: Any) -> Any:
            return _pins()

        def final_cleanup(self, *_args: Any) -> str:
            pytest.fail("legacy final cleanup")

    calls = 0

    def ambiguous(_plan: Any, _lease: Any, **_kwargs: Any) -> DurableFinalCleanupReceipt:
        nonlocal calls
        calls += 1
        raise OSError("uncertain after creating cleanup intent")

    monkeypatch.setattr(successor.cleanup_runtime, "execute_durable_final_cleanup", ambiguous)
    bridge = successor.OneShotFinalCleanupBridge(
        Delegate(),
        read_cleanup_coordinates=lambda *_: _cleanup_coordinates(tmp_path),
        verify_lease=_assert_lease,
    )
    lease = _lease()
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.completed_final_cleanup(_expected().plan, lease)
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.final_cleanup(_expected().plan, lease)
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.final_cleanup(_expected().plan, lease)
    assert calls == 1
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.completed_final_cleanup(_expected().plan, lease)


def test_cleanup_bridge_rejects_bare_accept_and_rebinding_of_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Delegate:
        def verify_release(self, *_args: Any) -> None: ...

        def retained_resources(self, *_args: Any) -> Any:
            return _pins()

        def final_cleanup(self, *_args: Any) -> str:
            pytest.fail("legacy final cleanup")

    evidence = _receipt()
    monkeypatch.setattr(
        successor.cleanup_runtime,
        "execute_durable_final_cleanup",
        lambda *_args, **_kwargs: evidence,
    )
    plan = _expected().plan
    lease = _lease()
    bridge = successor.OneShotFinalCleanupBridge(
        Delegate(),
        read_cleanup_coordinates=lambda *_: _cleanup_coordinates(tmp_path),
        verify_lease=_assert_lease,
    )
    assert bridge.final_cleanup(plan, lease) == "ACCEPT"
    assert bridge.completed_final_cleanup(plan, lease) is evidence
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.completed_final_cleanup(plan, _lease())
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.completed_final_cleanup(_expected().plan, lease)
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.final_cleanup(plan, lease)


def test_backend_cannot_accept_plain_cleanup_ack_without_same_call_typed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a malicious/buggy base ACK must not become ACCEPTED."""

    class Delegate:
        def verify_release(self, *_args: Any) -> None: ...

        def retained_resources(self, *_args: Any) -> Any:
            return _pins()

        def final_cleanup(self, *_args: Any) -> str:
            pytest.fail("legacy cleanup should never be called")

    bridge = successor.OneShotFinalCleanupBridge(
        Delegate(),
        read_cleanup_coordinates=lambda *_: _cleanup_coordinates(tmp_path),
        verify_lease=_assert_lease,
    )
    backend = successor.PostflightGatedSuccessorBackend(
        _sources(), _pins(), bridge, gate=_gate(tmp_path)
    )
    monkeypatch.setattr(
        reusable.ReusablePairUpgradeBackend, "finalize", lambda *_a, **_kw: "ACCEPT"
    )
    assert (
        backend.finalize(
            _expected().plan,
            commit_started=True,
            controller_id="c" * 64,
            worker_id="d" * 64,
            lease=_lease(),
        )
        == "INDETERMINATE"
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ("no-context", "bare-ack", "digest-corrupt"))
def test_cleanup_bridge_refuses_missing_context_bare_ack_and_wrong_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from dataclasses import replace

    class Delegate:
        def verify_release(self, *_args: Any) -> None: ...

        def retained_resources(self, *_args: Any) -> Any:
            return _pins()

        def final_cleanup(self, *_args: Any) -> str:
            pytest.fail("legacy cleanup")

    evidence: Any = "ACCEPT" if failure == "bare-ack" else replace(_receipt(), sha256="0" * 64)
    calls: list[int] = []

    def fake_cleanup(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(1)
        return evidence

    monkeypatch.setattr(successor.cleanup_runtime, "execute_durable_final_cleanup", fake_cleanup)
    bridge = successor.OneShotFinalCleanupBridge(
        Delegate(),
        read_cleanup_coordinates=(
            None if failure == "no-context" else lambda *_: _cleanup_coordinates(tmp_path)
        ),
        verify_lease=_assert_lease,
    )
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.final_cleanup(_expected().plan, _lease())
    with pytest.raises(successor.SuccessorFinalizationNoGo):
        bridge.final_cleanup(_expected().plan, _lease())
    assert calls == ([] if failure == "no-context" else [1])
