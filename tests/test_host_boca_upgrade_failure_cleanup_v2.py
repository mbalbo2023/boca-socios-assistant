"""Future successor FAILURE cleanup: offline same-lease, exact Boca-only policy."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as gc
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure
from boca_socios import host_cutover_stage as stage
from boca_socios import host_on_demand_service as service
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_pair_upgrade_reusable import _plan

INTENT_NAME, RECEIPT_NAME = failure.failure_cleanup_filenames(_plan().attempt_id)

BOCA_LABEL = (("com.docker.compose.project", "boca-socios"),)
CONTROLLER_MOUNTS = tuple(
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
WORKER_MOUNTS = ("boca-socios_boca_site_config", "boca-socios_boca_browser_ipc")
OLD_CONTROLLER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "3" * 64
OLD_WORKER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "4" * 64
NEW_CONTROLLER = "6" * 64
NEW_CONTROLLER_IMAGE = "sha256:" + "7" * 64


def _r108() -> gc.HistoricalRetainedImageProof:
    return gc.HistoricalRetainedImageProof(
        gc.HISTORICAL_RETIRE_TARGET,
        gc.HISTORICAL_RETIRE_DIGEST,
        gc.HISTORICAL_RETIRE_REVISION,
    )


def _installed() -> OnDemandInstallation:
    plan = _plan()
    return OnDemandInstallation(
        plan.old_attempt_id,
        plan.old_source_sha,
        plan.old_controller_id,
        OLD_CONTROLLER_REF,
        plan.old_worker_id,
        OLD_WORKER_REF,
        binding.CANONICAL_DATABASE,
        ReviewedInstalledPair(plan.old_attempt_id, "5" * 64, "8" * 64),
    )


def _inventory(*, candidate: bool = False, candidate_running: bool = False) -> gc.Inventory:
    plan = _plan()
    old = _installed()
    old_controller = gc.Container(
        plan.old_controller_id,
        "/boca-socios-controller-1",
        plan.old_controller_image_id,
        True,
        (
            *BOCA_LABEL,
            ("com.docker.compose.service", "controller"),
            ("boca.socios.browser-ipc-attempt", plan.old_attempt_id),
            ("org.opencontainers.image.revision", plan.old_source_sha),
            ("com.docker.compose.config-hash", old.pair.controller_config_hash),
        ),
        CONTROLLER_MOUNTS,
        ("boca-socios_boca_private",),
    )
    old_worker = gc.Container(
        plan.old_worker_id,
        "/boca-socios-browser-worker-1",
        plan.old_worker_image_id,
        False,
        (
            *BOCA_LABEL,
            ("com.docker.compose.service", "browser-worker"),
            ("boca.socios.browser-ipc-attempt", plan.old_attempt_id),
            ("org.opencontainers.image.revision", plan.old_source_sha),
            ("com.docker.compose.config-hash", old.pair.worker_config_hash),
        ),
        WORKER_MOUNTS,
        ("boca-socios_boca_browser_egress",),
    )
    candidate_container = gc.Container(
        NEW_CONTROLLER,
        "/boca-socios-controller-candidate",
        NEW_CONTROLLER_IMAGE,
        candidate_running,
        (
            *BOCA_LABEL,
            ("com.docker.compose.service", "controller"),
            ("boca.socios.browser-ipc-attempt", plan.attempt_id),
            ("org.opencontainers.image.revision", plan.new_source_sha),
            ("com.docker.compose.config-hash", "a" * 64),
        ),
        (),
        (),
    )
    images = (
        gc.Image(plan.old_controller_image_id, (OLD_CONTROLLER_REF,), gc.BOCA_SOURCE),
        gc.Image(plan.old_worker_image_id, (OLD_WORKER_REF,), gc.BOCA_SOURCE),
        gc.Image(
            gc.HISTORICAL_RETIRE_TARGET,
            ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",),
            None,
        ),
    ) + (
        (gc.Image(NEW_CONTROLLER_IMAGE, (plan.controller_ref,), gc.BOCA_SOURCE),)
        if candidate
        else ()
    )
    containers = (old_controller, old_worker) + ((candidate_container,) if candidate else ())
    networks = (
        gc.Network("boca-socios_boca_private", "9" * 64, (plan.old_controller_id,), BOCA_LABEL),
        gc.Network(
            "boca-socios_boca_browser_egress",
            "5" * 64,
            (),
            (
                *BOCA_LABEL,
                ("com.docker.compose.network", "boca_browser_egress"),
                ("boca.socios.browser-ipc-attempt", "43217075287"),
            ),
        ),
    )
    volumes = tuple(
        gc.Volume(
            name,
            (
                *BOCA_LABEL,
                (
                    "com.docker.compose.volume",
                    "boca_browser_ipc" if name.endswith("browser_ipc") else "boca_site_config",
                ),
                (
                    "boca.socios.browser-ipc-attempt",
                    "42806447101" if name.endswith("browser_ipc") else "43217075287",
                ),
            )
            if name in ("boca-socios_boca_browser_ipc", "boca-socios_boca_site_config")
            else BOCA_LABEL,
        )
        for name in CONTROLLER_MOUNTS
    )
    disk = gc.DiskInodes(1_000_000, 10_000, 2_000_000, 20_000, 3, 4, 5, 6)
    return gc.Inventory(
        containers,
        images,
        networks,
        volumes,
        disk,
        frozenset(image.ident for image in images),
    )


def _canon(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


class _TrustedRetainedIO:
    """Explicit synthetic R188 reader; never consults host Docker or filesystem."""

    def rootless_identity(self) -> tuple[int, int, str]:
        return (10001, 10001, "/home/boca-deploy/.local/share/docker")

    def inventory(self) -> gc.Inventory:
        return _inventory()

    def identity(self, name: str) -> str:
        if name == "boca-socios_boca_browser_ipc":
            return "3" * 64
        if name == "boca-socios_boca_site_config":
            return "4" * 64
        raise AssertionError("unexpected retained identity read")

    def mounts(self, ident: str) -> object:
        controller = ident == _plan().old_controller_id
        if not controller and ident != _plan().old_worker_id:
            raise AssertionError("unexpected candidate mounts read")
        roles = (
            (
                ("boca-socios_boca_data", "/data", True),
                ("boca-socios_boca_key", "/run/secrets", False),
                ("boca-socios_boca_owner", "/run/owner", False),
                ("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", False),
                ("boca-socios_boca_site_config", "/run/boca-site-config", True),
            )
            if controller
            else (
                ("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", True),
                ("boca-socios_boca_site_config", "/run/boca-site-config", False),
            )
        )
        result: list[dict[str, object]] = [
            {"Type": "volume", "Name": name, "Destination": destination, "RW": rw}
            for name, destination, rw in roles
        ]
        if controller:
            result.append(
                {
                    "Type": "bind",
                    "Source": "/home/boca-deploy/.boca-on-demand/socket",
                    "Destination": "/run/boca-bot-control",
                    "RW": False,
                    "Propagation": "rprivate",
                }
            )
        return result

    def worker_state(self, ident: str) -> object:
        if ident != _plan().old_worker_id:
            raise AssertionError("unexpected worker state read")
        return {"Status": "created", "Running": False, "Pid": 0, "ExitCode": 0}


_TRUSTED_IO = _TrustedRetainedIO()


def _journal(directory: Path, *, wrong_attempt: bool = False) -> None:
    plan = _plan()
    evidence = _canon(
        {
            "version": "boca-successor-pair-intent-evidence-v1",
            "plan": asdict(plan),
            "release": {
                "source_sha": plan.new_source_sha,
                "release_run_id": plan.release_run_id,
                "controller_ref": plan.controller_ref,
                "worker_ref": plan.worker_ref,
                "controller_manifest_sha256": "a" * 64,
                "paired_manifest_sha256": "b" * 64,
            },
            "witness": {
                "observation_run_id": plan.observation_run_id,
                "old_attempt_id": plan.old_attempt_id,
                "old_source_sha": plan.old_source_sha,
                "controller_id": plan.old_controller_id,
                "worker_id": plan.old_worker_id,
                "controller_image_id": plan.old_controller_image_id,
                "worker_image_id": plan.old_worker_image_id,
                "control_inode_sha256": "c" * 64,
                "retained": {
                    "ipc_creator_attempt": "42806447101",
                    "ipc_inode_sha256": "3" * 64,
                    "site_creator_attempt": "43217075287",
                    "site_inode_sha256": "4" * 64,
                    "egress_creator_attempt": "43217075287",
                    "egress_id": "5" * 64,
                },
            },
        }
    )
    original_intent = _canon(
        {
            "attempt": "9" * 11 if wrong_attempt else plan.attempt_id,
            "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "old_controller": plan.old_controller_id,
            "old_worker": plan.old_worker_id,
            "old_source": plan.old_source_sha,
            "new_source": plan.new_source_sha,
            "release": plan.release_run_id,
        }
    )
    stem = f".boca-pair-upgrade-{plan.attempt_id}"
    (directory / f"{stem}.evidence").write_bytes(evidence)
    (directory / f"{stem}.intent").write_bytes(original_intent)
    (directory / f"{stem}.evidence").chmod(0o600)
    (directory / f"{stem}.intent").chmod(0o600)


@pytest.fixture
def lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> gc.BocaJobLease:
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir(mode=0o700)
    stage_dir = tmp_path / "receipt"
    stage_dir.mkdir(mode=0o700)
    monkeypatch.setattr(gc, "LEASE_DIR", lock_dir)
    monkeypatch.setattr(gc, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(stage, "ROOT", stage_dir)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    monkeypatch.setattr(gc, "attest_historical_retained_image", lambda *_a, **_k: _r108())
    with gc.protected_boca_job_lease(_plan().attempt_id) as held:
        yield held


def _run(
    lease: gc.BocaJobLease,
    *,
    restored: bool = True,
    retained_io: adapters.RetainedResourceIO | None = _TRUSTED_IO,
) -> failure.DurableFailureCleanupReceipt:
    return failure.execute_durable_failure_cleanup(
        _plan(),
        lease,
        restored=restored,
        receipt_dir=stage.ROOT,
        historical_retained=_r108(),
        retained_io=retained_io,
    )


def test_missing_original_successor_journal_refuses_before_docker_inventory(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    monkeypatch.setattr(
        gc, "capture_inventory", lambda: pytest.fail("unsafe inventory before journal")
    )
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease)
    assert not (stage.ROOT / INTENT_NAME).exists()


def test_unrestored_failure_writes_durable_no_go_without_deletions(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    before = _inventory(candidate=True)
    monkeypatch.setattr(gc, "capture_inventory", lambda: before)
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("unrestored failure deletion"))
    monkeypatch.setattr(
        service, "read_installed_binding", lambda *_: pytest.fail("no restored state")
    )
    proof = _run(lease, restored=False)
    assert proof.state == "NO_GO"
    assert proof.apply_authorized is False
    assert proof.cleanup_status == "NO_GO"
    parsed = counted.verify_cleanup_v2_receipt(
        proof.raw, _plan().attempt_id, require_install_success=False
    )
    assert parsed["outcome"] == "FAILURE"
    assert parsed["removed"] == []
    assert parsed["before_counts"] == parsed["after_counts"]
    assert (stage.ROOT / RECEIPT_NAME).read_bytes() == proof.raw
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=False)


def test_restored_failure_deletes_only_stopped_attempt_pair_and_its_unused_image(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    deletions: list[gc.Target] = []
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())

    def probe() -> gc.Inventory:
        return current

    def exact_delete(target: gc.Target) -> None:
        nonlocal current
        deletions.append(target)
        if target.kind == "container" and target.ident == NEW_CONTROLLER:
            current = replace(
                current,
                containers=tuple(c for c in current.containers if c.ident != NEW_CONTROLLER),
            )
        elif target.kind == "image" and target.ident == NEW_CONTROLLER_IMAGE:
            current = replace(
                current,
                images=tuple(i for i in current.images if i.ident != NEW_CONTROLLER_IMAGE),
                global_image_ids=current.global_image_ids - {NEW_CONTROLLER_IMAGE},
            )
        else:
            pytest.fail(f"unallowlisted exact deletion {target.kind}")

    monkeypatch.setattr(gc, "capture_inventory", probe)
    monkeypatch.setattr(gc, "delete_exact", exact_delete)
    result = _run(lease, restored=True)
    assert result.state == "NO_GO"
    assert result.apply_authorized is False
    assert result.cleanup_status == "ACCEPT"
    assert deletions == [
        gc.Target("container", NEW_CONTROLLER),
        gc.Target("image", NEW_CONTROLLER_IMAGE),
    ]
    receipt = counted.verify_cleanup_v2_receipt(
        result.raw, _plan().attempt_id, require_install_success=False
    )
    assert receipt["outcome"] == "FAILURE"
    assert receipt["protected_pair"] is None
    assert receipt["removed"] == [
        {"kind": "container", "id": NEW_CONTROLLER},
        {"kind": "image", "id": NEW_CONTROLLER_IMAGE},
    ]
    assert {c.ident for c in current.containers} == {
        _plan().old_controller_id,
        _plan().old_worker_id,
    }
    assert {volume.name for volume in current.volumes} == set(CONTROLLER_MOUNTS)
    assert gc.HISTORICAL_RETIRE_TARGET in current.global_image_ids
    with pytest.raises(gc.CleanupError):
        counted.verify_cleanup_v2_receipt(result.raw, _plan().attempt_id)


@pytest.mark.parametrize(
    "case", ["running_candidate", "binding_drift", "changed_role", "commit_exists"]
)
def test_uncertain_or_postcommit_restoration_blocks_all_deletions(
    case: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    current = _inventory(candidate=True, candidate_running=case == "running_candidate")
    if case == "changed_role":
        candidate = current.containers[-1]
        current = replace(
            current,
            containers=(
                *current.containers[:-1],
                replace(
                    candidate,
                    labels=(
                        *candidate.labels[:-1],
                        ("org.opencontainers.image.revision", _plan().old_source_sha),
                    ),
                ),
            ),
        )
    if case == "commit_exists":
        (stage.ROOT / f".boca-pair-upgrade-{_plan().attempt_id}.commit").write_bytes(b"commit")
    binding = _installed()
    if case == "binding_drift":
        binding = replace(binding, worker_id="f" * 64)
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: binding)
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("uncertain deletion"))
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert not (stage.ROOT / RECEIPT_NAME).exists()


def test_wrong_original_attempt_rejects_before_any_cleanup_effect(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT, wrong_attempt=True)
    monkeypatch.setattr(gc, "capture_inventory", lambda: pytest.fail("wrong journal inventory"))
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("wrong journal deletion"))
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert not (stage.ROOT / INTENT_NAME).exists()


def test_unexpected_new_unused_image_cannot_be_deleted_by_generic_engine(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    base = _inventory(candidate=False)
    unapproved = gc.Image(
        "sha256:" + "0" * 64,
        ("ghcr.io/mbalbo2023/boca-socios-assistant:sha-" + "d" * 40,),
        gc.BOCA_SOURCE,
    )
    calls = 0

    def probe() -> gc.Inventory:
        nonlocal calls
        calls += 1
        if calls <= 2:
            return base
        return replace(
            base,
            images=(*base.images, unapproved),
            global_image_ids=base.global_image_ids | {unapproved.ident},
        )

    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", probe)
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("unknown image deletion"))
    receipt = _run(lease, restored=True)
    assert receipt.state == "NO_GO"
    assert receipt.cleanup_status == "NO_GO"
    assert receipt.apply_authorized is False
    assert (
        counted.verify_cleanup_v2_receipt(
            receipt.raw, _plan().attempt_id, require_install_success=False
        )["outcome"]
        == "FAILURE"
    )


def test_original_journal_symlink_and_replay_are_rejected(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease, tmp_path: Path
) -> None:
    _journal(stage.ROOT)
    original = stage.ROOT / f".boca-pair-upgrade-{_plan().attempt_id}.intent"
    copy = tmp_path / "intent-backup"
    copy.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(copy)
    monkeypatch.setattr(gc, "capture_inventory", lambda: pytest.fail("symlink journal"))
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=False)
    assert not (stage.ROOT / INTENT_NAME).exists()


def test_new_attempt_does_not_replay_an_unrelated_old_failure_receipt(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    old_intent, old_receipt = failure.failure_cleanup_filenames("43217075289")
    (stage.ROOT / old_intent).write_bytes(b"old consumed attempt")
    (stage.ROOT / old_receipt).write_bytes(b"old terminal")
    monkeypatch.setattr(gc, "capture_inventory", lambda: _inventory(candidate=False))
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("no restored proof"))
    proof = _run(lease, restored=False)
    assert proof.state == "NO_GO"
    assert (stage.ROOT / RECEIPT_NAME).exists()
    assert (stage.ROOT / old_receipt).read_bytes() == b"old terminal"


def test_r108_provenance_drift_refuses_before_any_deletion(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    monkeypatch.setattr(gc, "capture_inventory", lambda: _inventory(candidate=True))
    monkeypatch.setattr(
        gc, "attest_historical_retained_image", lambda *_a: replace(_r108(), revision="0" * 40)
    )
    monkeypatch.setattr(gc, "delete_exact", lambda *_: pytest.fail("R108 drift deletion"))
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=False)
    assert (stage.ROOT / INTENT_NAME).exists()
    assert not (stage.ROOT / RECEIPT_NAME).exists()


@pytest.mark.parametrize("lost", ["lease", "binding"])
def test_proof_lost_after_first_exact_removal_stops_before_second(
    lost: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    installed = _installed()
    deleted: list[gc.Target] = []
    binding = [installed]
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: binding[0])
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)

    def delete(target: gc.Target) -> None:
        nonlocal current
        deleted.append(target)
        if len(deleted) > 1:
            pytest.fail("continued cleanup after loss of protected evidence")
        assert target == gc.Target("container", NEW_CONTROLLER)
        current = replace(
            current, containers=tuple(c for c in current.containers if c.ident != NEW_CONTROLLER)
        )
        if lost == "lease":
            lease.active = False
        else:
            binding[0] = replace(installed, worker_id="f" * 64)

    monkeypatch.setattr(gc, "delete_exact", delete)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert deleted == [gc.Target("container", NEW_CONTROLLER)]
    assert (stage.ROOT / INTENT_NAME).exists()
    assert not (stage.ROOT / RECEIPT_NAME).exists()


def test_only_attempt_owned_unused_disposable_network_and_volume_are_removed(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    _journal(stage.ROOT)
    attempt = (("boca.socios.browser-ipc-attempt", _plan().attempt_id),)
    disposable = gc.Volume("boca-socios_temporary_r247", (*BOCA_LABEL, *attempt))
    disposable_net = gc.Network("boca-socios_r247_temp", "7" * 64, (), (*BOCA_LABEL, *attempt))
    current = _inventory(candidate=False)
    current = replace(
        current,
        volumes=(*current.volumes, disposable),
        networks=(*current.networks, disposable_net),
    )
    deletions: list[gc.Target] = []
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)

    def exact_delete(target: gc.Target) -> None:
        nonlocal current
        deletions.append(target)
        if target == gc.Target("volume", disposable.name):
            current = replace(
                current,
                volumes=tuple(x for x in current.volumes if x.name != disposable.name),
            )
        elif target == gc.Target("network", disposable_net.ident):
            current = replace(
                current,
                networks=tuple(x for x in current.networks if x.ident != disposable_net.ident),
            )
        else:
            pytest.fail("attempt cleanup touched retained or foreign resource")

    monkeypatch.setattr(gc, "delete_exact", exact_delete)
    proof = _run(lease, restored=True)
    assert proof.state == "NO_GO"
    assert proof.cleanup_status == "ACCEPT"
    assert deletions == [
        gc.Target("volume", disposable.name),
        gc.Target("network", disposable_net.ident),
    ]
    assert {v.name for v in current.volumes} == set(CONTROLLER_MOUNTS)


@pytest.mark.parametrize("kind", ["volume", "network"])
def test_attempt_target_owner_swap_between_plan_and_delete_must_not_delete(
    kind: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """The exact target name/ID must not authorize another attempt's object."""
    _journal(stage.ROOT)
    attempt_labels = (*BOCA_LABEL, ("boca.socios.browser-ipc-attempt", _plan().attempt_id))
    foreign_labels = (*BOCA_LABEL, ("boca.socios.browser-ipc-attempt", "99999999999"))
    target_volume = gc.Volume("boca-socios_temporary_r247", attempt_labels)
    target_network = gc.Network("boca-socios_r247_temp", "7" * 64, (), attempt_labels)
    current = _inventory(candidate=False)
    current = replace(
        current,
        volumes=(*current.volumes, target_volume) if kind == "volume" else current.volumes,
        networks=(*current.networks, target_network) if kind == "network" else current.networks,
    )
    observations = 0
    deletions: list[gc.Target] = []

    def probe() -> gc.Inventory:
        nonlocal observations
        observations += 1
        if observations < 5:
            return current
        if kind == "volume":
            return replace(
                current,
                volumes=(*current.volumes[:-1], replace(target_volume, labels=foreign_labels)),
            )
        return replace(
            current,
            networks=(*current.networks[:-1], replace(target_network, labels=foreign_labels)),
        )

    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", probe)
    monkeypatch.setattr(gc, "delete_exact", deletions.append)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert observations >= 5
    assert deletions == []


@pytest.mark.parametrize("drift", ["foreign_reference", "missing_source"])
def test_attempt_image_identity_drift_before_delete_preserves_image(
    drift: str, monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """A candidate image ID alone cannot authorize removal after its identity changes."""
    _journal(stage.ROOT)
    current = replace(_inventory(candidate=True), containers=_inventory().containers)
    observations = 0
    deletions: list[gc.Target] = []

    def probe() -> gc.Inventory:
        nonlocal observations
        observations += 1
        images = [image for image in current.images if image.ident == NEW_CONTROLLER_IMAGE]
        if observations < 5 or not images:
            return current
        candidate_image = images[0]
        replacement = (
            replace(candidate_image, references=("foreign.example/independent-service:live",))
            if drift == "foreign_reference"
            else replace(candidate_image, source=None)
        )
        return replace(current, images=(*current.images[:-1], replacement))

    def delete(target: gc.Target) -> None:
        nonlocal current
        deletions.append(target)
        if target == gc.Target("image", NEW_CONTROLLER_IMAGE):
            current = replace(
                current,
                images=tuple(i for i in current.images if i.ident != NEW_CONTROLLER_IMAGE),
                global_image_ids=current.global_image_ids - {NEW_CONTROLLER_IMAGE},
            )
        else:
            pytest.fail("attempt cleanup touched unrelated resource")

    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", probe)
    monkeypatch.setattr(gc, "delete_exact", delete)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert observations >= 5
    assert deletions == []


def test_restored_worker_on_private_bridge_cannot_authorize_any_cleanup(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """Wrong restored network topology must refuse before first deletion."""
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    worker = current.containers[1]
    private, egress = current.networks
    current = replace(
        current,
        containers=(
            current.containers[0],
            replace(worker, networks=("boca-socios_boca_private",)),
            current.containers[2],
        ),
        networks=(
            replace(private, attached_ids=(current.containers[0].ident, worker.ident)),
            replace(egress, attached_ids=()),
        ),
    )
    deletions: list[gc.Target] = []
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)
    monkeypatch.setattr(gc, "delete_exact", deletions.append)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, restored=True)
    assert deletions == []


def test_restoration_without_live_retained_inode_witness_cannot_delete(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """The old journal's pinned inode hashes are not current host evidence."""
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    deletions: list[gc.Target] = []
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)
    monkeypatch.setattr(gc, "delete_exact", deletions.append)
    with pytest.raises(failure.FailureCleanupNoGo):
        failure.execute_durable_failure_cleanup(
            _plan(), lease, restored=True, receipt_dir=stage.ROOT, historical_retained=_r108()
        )
    assert deletions == []


def test_restored_site_inode_changed_since_original_witness_refuses_deletion(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """The original journal alone cannot attest the CURRENT SITE volume inode."""
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    deletions: list[gc.Target] = []

    class DriftedSiteIO(_TrustedRetainedIO):
        def identity(self, name: str) -> str:
            if name == "boca-socios_boca_site_config":
                return "f" * 64
            return super().identity(name)

    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)
    monkeypatch.setattr(gc, "delete_exact", deletions.append)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease, retained_io=DriftedSiteIO())
    assert deletions == []


def test_restored_egress_id_must_still_match_original_witness(
    monkeypatch: pytest.MonkeyPatch, lease: gc.BocaJobLease
) -> None:
    """Restoration of a same-named replacement egress bridge is not proven."""
    _journal(stage.ROOT)
    current = _inventory(candidate=True)
    current = replace(
        current,
        networks=(current.networks[0], replace(current.networks[1], ident="e" * 64)),
    )
    deletions: list[gc.Target] = []
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed())
    monkeypatch.setattr(gc, "capture_inventory", lambda: current)
    monkeypatch.setattr(gc, "delete_exact", deletions.append)
    with pytest.raises(failure.FailureCleanupNoGo):
        _run(lease)
    assert deletions == []
