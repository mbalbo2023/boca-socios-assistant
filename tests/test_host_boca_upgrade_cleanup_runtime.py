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
    OLD_IMAGE,
    WORKER,
    WORKER_IMAGE,
    _completed,
    _historical,
)
from test_host_boca_pair_upgrade_reusable import _plan

INTENT_FILE, RECEIPT_FILE = runtime.final_cleanup_filenames(_plan().attempt_id)


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
    controller_mounts = tuple(
        sorted(
            (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
                "boca-socios_boca_site_config",
                "boca-socios_boca_browser_ipc",
            )
        )
    )
    worker_mounts = (
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    )

    def complete_mounts(snapshot: gc.Inventory) -> gc.Inventory:
        controller, worker = snapshot.containers
        return replace(
            _historical(snapshot),
            containers=(
                replace(controller, volumes=controller_mounts),
                replace(worker, volumes=worker_mounts),
            ),
            volumes=(*snapshot.volumes, extra),
        )

    before = complete_mounts(before)
    after = complete_mounts(after)
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


@pytest.mark.parametrize(
    "drift",
    [
        "foreign_alias",
        "boca_alias",
        "source_lost",
        "source_foreign",
        "container_reference",
        "image_disappeared",
    ],
)
def test_success_cleanup_refuses_image_identity_drift_between_plan_and_delete(
    drift: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    """An image ID cannot authorize removal after aliases/source or usage change."""
    current = _evidence().before
    observations = 0
    deletions: list[gc.Target] = []

    def drifted(snapshot: gc.Inventory) -> gc.Inventory:
        image = next(item for item in snapshot.images if item.ident == OLD_IMAGE)
        if drift == "image_disappeared":
            return replace(
                snapshot,
                images=tuple(item for item in snapshot.images if item.ident != OLD_IMAGE),
                global_image_ids=snapshot.global_image_ids - {OLD_IMAGE},
            )
        if drift == "container_reference":
            foreign = gc.Container(
                "9" * 64,
                "/boca-socios-other-service-1",
                OLD_IMAGE,
                False,
                BOCA_LABEL,
            )
            return replace(snapshot, containers=(*snapshot.containers, foreign))
        if drift == "foreign_alias":
            image = replace(image, references=(*image.references, "foreign.example/owner:live"))
        elif drift == "boca_alias":
            image = replace(
                image,
                references=(*image.references, "ghcr.io/mbalbo2023/boca-socios-assistant:other"),
            )
        elif drift == "source_foreign":
            image = replace(image, source="https://foreign.example/owner")
        else:
            image = replace(image, source=None)
        return replace(
            snapshot,
            images=tuple(image if item.ident == OLD_IMAGE else item for item in snapshot.images),
        )

    def capture() -> gc.Inventory:
        nonlocal current, observations
        observations += 1
        observed = current
        if observations == 3:
            # The second execute() probe has finished selecting the image.
            # OCI state changes before protected_delete() sees that target.
            current = drifted(current)
        return observed

    def delete(target: gc.Target) -> None:
        nonlocal current
        deletions.append(target)
        if target != gc.Target("image", OLD_IMAGE):
            pytest.fail("SUCCESS touched a resource outside the selected obsolete Boca image")
        current = replace(
            current,
            images=tuple(item for item in current.images if item.ident != OLD_IMAGE),
            global_image_ids=current.global_image_ids - {OLD_IMAGE},
        )

    def attest(snapshot: gc.Inventory) -> gc.HistoricalRetainedImageProof:
        assert gc.HISTORICAL_RETIRE_TARGET in snapshot.global_image_ids
        assert all(c.image_id != gc.HISTORICAL_RETIRE_TARGET for c in snapshot.containers)
        return _r108()

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "delete_exact", delete)
    monkeypatch.setattr(gc, "attest_historical_retained_image", attest)
    destination = _receipt_dir(tmp_path)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert observations >= 3
    assert deletions == []
    assert (destination / INTENT_FILE).is_file()
    assert not (destination / RECEIPT_FILE).exists()


def test_success_cleanup_stable_image_deletes_exact_id_and_retains_r108(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    """Opt-in image check still permits a genuinely unused Boca image cleanup."""
    current = _evidence().before
    deleted: list[gc.Target] = []
    observations = 0

    def capture() -> gc.Inventory:
        nonlocal observations
        observations += 1
        return current

    def delete(target: gc.Target) -> None:
        nonlocal current
        deleted.append(target)
        assert target == gc.Target("image", OLD_IMAGE)
        current = replace(
            current,
            images=tuple(image for image in current.images if image.ident != OLD_IMAGE),
            global_image_ids=current.global_image_ids - {OLD_IMAGE},
        )

    def attest(snapshot: gc.Inventory) -> gc.HistoricalRetainedImageProof:
        assert gc.HISTORICAL_RETIRE_TARGET in snapshot.global_image_ids
        assert all(c.image_id != gc.HISTORICAL_RETIRE_TARGET for c in snapshot.containers)
        return _r108()

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "delete_exact", delete)
    monkeypatch.setattr(gc, "attest_historical_retained_image", attest)
    destination = _receipt_dir(tmp_path)
    receipt = _run(lease, destination)
    assert receipt.status == "ACCEPT"
    assert deleted == [gc.Target("image", OLD_IMAGE)]
    assert observations >= 6  # R108 preprobe, before, selected, pre-delete, after, terminal.
    assert gc.HISTORICAL_RETIRE_TARGET in current.global_image_ids
    assert (destination / RECEIPT_FILE).read_bytes() == receipt.raw


def test_success_cleanup_lost_lease_after_fresh_image_probe_never_deletes(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    """Even a clean last OCI snapshot cannot authorize deletion after lease loss."""
    snapshot = _evidence().before
    observations = 0
    deleted: list[gc.Target] = []
    original_verify = gc.verify_protected_boca_job_lease

    def capture() -> gc.Inventory:
        nonlocal observations
        observations += 1
        return snapshot

    def check_lease(current: gc.BocaJobLease, attempt_id: str) -> None:
        original_verify(current, attempt_id)
        if observations >= 4:
            raise gc.CleanupError("lease lost after the immediate image revalidation")

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "delete_exact", deleted.append)
    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", check_lease)
    monkeypatch.setattr(gc, "attest_historical_retained_image", lambda _snapshot: _r108())
    destination = _receipt_dir(tmp_path)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert observations >= 4
    assert deleted == []
    assert (destination / INTENT_FILE).is_file()
    assert not (destination / RECEIPT_FILE).exists()


@pytest.mark.parametrize("kind", ["volume", "network"])
def test_success_cleanup_image_guard_does_not_change_other_resource_deletion(
    kind: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    """Network/volume cleanup retains the existing exact-target algorithm."""
    snapshot = _evidence().before
    snapshot = replace(
        snapshot,
        images=tuple(image for image in snapshot.images if image.ident != OLD_IMAGE),
        global_image_ids=snapshot.global_image_ids - {OLD_IMAGE},
    )
    labels = (*BOCA_LABEL, ("boca.socios.browser-ipc-attempt", _plan().attempt_id))
    volume = gc.Volume("boca-socios_cleanup_v2_ephemeral", labels)
    network = gc.Network("boca-socios_cleanup_v2_ephemeral", "8" * 64, (), labels)
    current = replace(
        snapshot,
        volumes=(*snapshot.volumes, volume) if kind == "volume" else snapshot.volumes,
        networks=(*snapshot.networks, network) if kind == "network" else snapshot.networks,
    )
    target = (
        gc.Target("volume", volume.name)
        if kind == "volume"
        else gc.Target("network", network.ident)
    )
    observations = 0
    deleted: list[gc.Target] = []

    def capture() -> gc.Inventory:
        nonlocal observations
        observations += 1
        return current

    def delete(observed: gc.Target) -> None:
        nonlocal current
        deleted.append(observed)
        assert observed == target
        current = replace(
            current,
            volumes=tuple(item for item in current.volumes if item.name != volume.name),
            networks=tuple(item for item in current.networks if item.ident != network.ident),
        )

    monkeypatch.setattr(gc, "capture_inventory", capture)
    monkeypatch.setattr(gc, "delete_exact", delete)
    monkeypatch.setattr(gc, "attest_historical_retained_image", lambda _snapshot: _r108())
    receipt = _run(lease, _receipt_dir(tmp_path))
    assert receipt.status == "ACCEPT"
    assert deleted == [target]
    assert observations == 6  # No extra pre-delete image probe for other resource kinds.
    assert gc.HISTORICAL_RETIRE_TARGET in current.global_image_ids


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
    assert (destination / INTENT_FILE).is_file()
    assert (destination / RECEIPT_FILE).read_bytes() == proof.raw
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
    assert (destination / INTENT_FILE).exists()
    assert not (destination / RECEIPT_FILE).exists()


def test_preexisting_terminal_refuses_to_enter_engine(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    destination = _receipt_dir(tmp_path)
    (destination / RECEIPT_FILE).write_bytes(b"previous evidence")

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
    assert not (destination / INTENT_FILE).exists()
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
    assert not (destination / INTENT_FILE).exists()


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
    assert (destination / INTENT_FILE).exists()
    assert not (destination / RECEIPT_FILE).exists()


@pytest.mark.parametrize(
    "case",
    [
        "controller_missing_ipc",
        "controller_missing_owner_sqlite_custody",
        "worker_missing_ipc",
        "worker_mounts_controller_data",
        "duplicate_worker_site_mount",
    ],
)
def test_durable_cleanup_rejects_protected_volume_disconnected_from_pair(
    case: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    """Existing volume names do not prove active SQLite/Chrome/IPC mounts.

    Both snapshots are mutated equally: the ordinary V2 before/after delta
    check cannot substitute the positive role-specific mount topology gate.
    """
    evidence = _evidence()

    def remove_mount(names: tuple[str, ...], name: str) -> tuple[str, ...]:
        return tuple(item for item in names if item != name)

    def corrupt(snapshot: gc.Inventory) -> gc.Inventory:
        controller, worker = snapshot.containers
        if case == "controller_missing_ipc":
            controller = replace(
                controller,
                volumes=remove_mount(controller.volumes, "boca-socios_boca_browser_ipc"),
            )
        elif case == "controller_missing_owner_sqlite_custody":
            controller = replace(
                controller,
                volumes=remove_mount(controller.volumes, "boca-socios_boca_owner"),
            )
        elif case == "worker_missing_ipc":
            worker = replace(
                worker,
                volumes=remove_mount(worker.volumes, "boca-socios_boca_browser_ipc"),
            )
        elif case == "worker_mounts_controller_data":
            worker = replace(worker, volumes=(*worker.volumes, "boca-socios_boca_data"))
        else:
            worker = replace(worker, volumes=(*worker.volumes, "boca-socios_boca_site_config"))
        return replace(snapshot, containers=(controller, worker))

    evidence = replace(evidence, before=corrupt(evidence.before), after=corrupt(evidence.after))
    calls = 0

    def fake_engine(*_args: object, **_kwargs: object) -> gc.ProtectedCleanupEvidence:
        nonlocal calls
        calls += 1
        return evidence

    monkeypatch.setattr(gc, "execute_protected_with_inventories", fake_engine)
    destination = _receipt_dir(tmp_path)
    with pytest.raises(runtime.FinalCleanupNoGo):
        _run(lease, destination)
    assert calls == 1
    assert (destination / INTENT_FILE).is_file()
    assert not (destination / RECEIPT_FILE).exists()


def test_success_cleanup_keeps_one_durable_journal_per_attempt_and_refuses_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A completed B→C cannot permanently block the independent C→D journal."""
    first, second = _plan(), replace(_plan(), attempt_id="44000000004")
    destination = _receipt_dir(tmp_path)
    cleanup_attempts: list[str] = []

    def verify_lease(lease: gc.BocaJobLease, attempt_id: str) -> None:
        assert lease.active and lease.attempt_id == attempt_id

    def execute(outcome: str, attempt_id: str, **kwargs: object) -> gc.ProtectedCleanupEvidence:
        assert outcome == "SUCCESS"
        cleanup_attempts.append(attempt_id)
        evidence = _evidence()
        return replace(evidence, receipt=replace(evidence.receipt, attempt_id=attempt_id))

    monkeypatch.setattr(gc, "verify_protected_boca_job_lease", verify_lease)
    monkeypatch.setattr(gc, "execute_protected_with_inventories", execute)

    for plan in (first, second):
        proof = runtime.execute_durable_final_cleanup(
            plan,
            gc.BocaJobLease(plan.attempt_id, -1, -1, True),
            controller_id=CONTROLLER,
            worker_id=WORKER,
            controller_image_id=CONTROLLER_IMAGE,
            worker_image_id=WORKER_IMAGE,
            receipt_dir=destination,
            historical_retained=_r108(),
        )
        assert proof.status == "ACCEPT"
        assert (destination / f"boca-final-cleanup-v2.{plan.attempt_id}.intent").is_file()
        assert (
            destination / f"boca-final-cleanup-v2.{plan.attempt_id}.receipt"
        ).read_bytes() == proof.raw

    with pytest.raises(runtime.FinalCleanupNoGo):
        runtime.execute_durable_final_cleanup(
            first,
            gc.BocaJobLease(first.attempt_id, -1, -1, True),
            controller_id=CONTROLLER,
            worker_id=WORKER,
            controller_image_id=CONTROLLER_IMAGE,
            worker_image_id=WORKER_IMAGE,
            receipt_dir=destination,
            historical_retained=_r108(),
        )
    assert cleanup_attempts == [first.attempt_id, second.attempt_id]
