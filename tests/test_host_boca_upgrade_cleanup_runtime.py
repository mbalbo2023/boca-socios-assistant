"""Offline successor cleanup bridge tests: no Docker/SSH/network calls."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as gc
from boca_socios import host_boca_upgrade_cleanup_runtime as runtime
from test_host_boca_cleanup_v2 import (
    BOCA_LABEL,
    CONTROLLER,
    CONTROLLER_IMAGE,
    WORKER,
    WORKER_IMAGE,
    _completed,
    _historical,
)
from test_host_boca_pair_upgrade_reusable import _plan


@pytest.fixture
def lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> gc.BocaJobLease:
    lock_dir = tmp_path / "lease"
    lock_dir.mkdir(mode=0o700)
    monkeypatch.setattr(gc, "LEASE_DIR", lock_dir)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    with gc.protected_boca_job_lease(_plan().attempt_id) as current:
        yield current


def _receipt_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "receipt"
    destination.mkdir(mode=0o700)
    return destination


def _r108() -> gc.HistoricalRetainedImageProof:
    return gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )


def _evidence() -> gc.ProtectedCleanupEvidence:
    receipt, before, after = _completed()
    extra = gc.Volume("boca-socios_boca_browser_ipc", BOCA_LABEL)
    before = replace(_historical(before), volumes=(*before.volumes, extra))
    after = replace(_historical(after), volumes=(*after.volumes, extra))
    return gc.ProtectedCleanupEvidence(
        replace(receipt, attempt_id=_plan().attempt_id, retained_attested=(_r108(),)),
        before,
        after,
    )


def _run(lease: gc.BocaJobLease, receipt_dir: Path) -> runtime.DurableFinalCleanupReceipt:
    return runtime.execute_durable_final_cleanup(
        _plan(),
        lease,
        controller_id=CONTROLLER,
        worker_id=WORKER,
        controller_image_id=CONTROLLER_IMAGE,
        worker_image_id=WORKER_IMAGE,
        receipt_dir=receipt_dir,
        historical_retained=_r108(),
    )


def test_one_shot_intent_and_v2_terminal_preserve_exact_pair(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    evidence = _evidence()

    def physical_engine(*_args: object, **kwargs: object) -> gc.ProtectedCleanupEvidence:
        calls.append(kwargs)
        return evidence

    monkeypatch.setattr(gc, "execute_protected_with_inventories", physical_engine)
    destination = _receipt_dir(tmp_path)
    proof = _run(lease, destination)
    assert proof.attempt_id == _plan().attempt_id
    assert proof.status == "ACCEPT"
    assert len(calls) == 1
    assert calls[0]["preserve_containers"] == frozenset({CONTROLLER, WORKER})
    assert calls[0]["preserve_images"] == frozenset({CONTROLLER_IMAGE, WORKER_IMAGE})
    assert calls[0]["historical_retained"] == _r108()
    assert calls[0]["retire_containers"] == frozenset()
    assert (destination / runtime.INTENT_FILENAME).is_file()
    assert (destination / runtime.RECEIPT_FILENAME).read_bytes() == proof.raw
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "case",
    ["swapped_roles", "missing_site_volume", "worker_started", "historical_absent"],
)
def test_posteffect_inventory_rejects_untrusted_accept(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    lease: gc.BocaJobLease,
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    if case == "missing_site_volume":
        evidence = replace(
            evidence,
            after=replace(
                evidence.after,
                volumes=tuple(
                    item
                    for item in evidence.after.volumes
                    if item.name != "boca-socios_boca_site_config"
                ),
            ),
        )
    elif case == "worker_started":
        evidence = replace(
            evidence,
            after=replace(
                evidence.after,
                containers=(
                    evidence.after.containers[0],
                    replace(evidence.after.containers[1], running=True),
                ),
            ),
        )
    elif case == "historical_absent":
        evidence = replace(
            evidence,
            receipt=replace(evidence.receipt, retained_attested=()),
            before=replace(
                evidence.before,
                images=tuple(
                    item
                    for item in evidence.before.images
                    if item.ident != gc.HISTORICAL_RETIRE_TARGET
                ),
                global_image_ids=evidence.before.global_image_ids - {gc.HISTORICAL_RETIRE_TARGET},
            ),
            after=replace(
                evidence.after,
                images=tuple(
                    item
                    for item in evidence.after.images
                    if item.ident != gc.HISTORICAL_RETIRE_TARGET
                ),
                global_image_ids=evidence.after.global_image_ids - {gc.HISTORICAL_RETIRE_TARGET},
            ),
        )

    calls = 0

    def simulated_engine(*_args: object, **_kwargs: object) -> gc.ProtectedCleanupEvidence:
        nonlocal calls
        calls += 1
        return evidence

    monkeypatch.setattr(gc, "execute_protected_with_inventories", simulated_engine)
    destination = _receipt_dir(tmp_path)
    if case == "swapped_roles":
        with pytest.raises(runtime.FinalCleanupNoGo):
            runtime.execute_durable_final_cleanup(
                _plan(),
                lease,
                controller_id=WORKER,
                worker_id=CONTROLLER,
                controller_image_id=WORKER_IMAGE,
                worker_image_id=CONTROLLER_IMAGE,
                receipt_dir=destination,
                historical_retained=_r108(),
            )
    else:
        with pytest.raises(runtime.FinalCleanupNoGo):
            _run(lease, destination)
    assert calls == 1
    assert (destination / runtime.INTENT_FILENAME).exists()
    assert not (destination / runtime.RECEIPT_FILENAME).exists()


def test_preexisting_terminal_refuses_to_enter_engine(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    destination = _receipt_dir(tmp_path)
    (destination / runtime.RECEIPT_FILENAME).write_bytes(b"previous evidence")

    def no_side_effects(*_args: object, **_kwargs: object) -> gc.ProtectedCleanupEvidence:
        pytest.fail("preexisting receipt must block cleanup before host effects")

    monkeypatch.setattr(gc, "execute_protected_with_inventories", no_side_effects)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)


def test_refuses_unsafe_directory_and_unauthenticated_r108_before_engine(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    destination = _receipt_dir(tmp_path)

    def no_side_effects(*_args: object, **_kwargs: object) -> gc.ProtectedCleanupEvidence:
        pytest.fail("invalid precondition must block cleanup")

    monkeypatch.setattr(gc, "execute_protected_with_inventories", no_side_effects)
    destination.chmod(0o755)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert not (destination / runtime.INTENT_FILENAME).exists()
    destination.chmod(0o700)
    with pytest.raises(runtime.FinalCleanupNoGo):
        runtime.execute_durable_final_cleanup(
            _plan(),
            lease,
            controller_id=CONTROLLER,
            worker_id=WORKER,
            controller_image_id=CONTROLLER_IMAGE,
            worker_image_id=WORKER_IMAGE,
            receipt_dir=destination,
            historical_retained=replace(_r108(), revision="0" * 40),
        )
    assert not (destination / runtime.INTENT_FILENAME).exists()


def test_lost_lease_after_engine_never_writes_terminal(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    evidence = _evidence()
    was_run = False
    original = gc.verify_protected_boca_job_lease

    def simulated_engine(*_args: object, **_kwargs: object) -> gc.ProtectedCleanupEvidence:
        nonlocal was_run
        was_run = True
        return evidence

    def check_lease(current: gc.BocaJobLease, attempt_id: str) -> None:
        if was_run:
            raise ValueError("lost lease after engine")
        original(current, attempt_id)

    monkeypatch.setattr(gc, "execute_protected_with_inventories", simulated_engine)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", check_lease)
    destination = _receipt_dir(tmp_path)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert was_run
    assert (destination / runtime.INTENT_FILENAME).exists()
    assert not (destination / runtime.RECEIPT_FILENAME).exists()
