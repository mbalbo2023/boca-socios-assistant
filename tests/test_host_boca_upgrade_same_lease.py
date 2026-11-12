"""Successor capture: current Boca rootless witnesses, never a host mutation."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_postcommit as installed
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_same_lease as capture
from boca_socios import host_cutover_stage as stage
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_pair_observe import (
    CONTROLLER_ID,
    CTRL_IMAGE_ID,
    WORKER_ID,
    WORKER_IMAGE_ID,
    _run,
)
from test_host_boca_upgrade_adapters import RetainedIO, seed
from test_host_boca_upgrade_retained_bridge import (
    MAIN as AUTH_MAIN,
)
from test_host_boca_upgrade_retained_bridge import (
    PAIR_RUN as AUTH_PAIR_RUN,
)
from test_host_boca_upgrade_retained_bridge import (
    RELEASE_RUN as AUTH_RELEASE_RUN,
)
from test_host_boca_upgrade_retained_bridge import (
    RETAINED_RUN as AUTH_RETAINED_RUN,
)
from test_host_boca_upgrade_retained_bridge import (
    _auth as authenticated_artifacts,
)

OLD_RUN = "44000000001"
NEW_RUN = "44000000003"
RELEASE_RUN = "44000000004"
_BASE_PAIR = json.loads(_run().removeprefix(pair._PREFIX))
_CUSTODY = seed()  # Genuine synthetic authenticator fixture, before lease UID override.


def old_receipt(run_id: str = OLD_RUN) -> bytes:
    value = copy.deepcopy(_BASE_PAIR)
    value.update(
        source_sha=installed.SOURCE_SHA,
        attempt_id=installed.FAILED_ATTEMPT,
        observation_run_id=run_id,
    )
    return pair._canonical(value)


def plan() -> transaction.PairCoordinates:
    return transaction.PairCoordinates(
        NEW_RUN,
        OLD_RUN,
        installed.FAILED_ATTEMPT,
        installed.SOURCE_SHA,
        CONTROLLER_ID,
        WORKER_ID,
        CTRL_IMAGE_ID,
        WORKER_IMAGE_ID,
        "a" * 40,
        RELEASE_RUN,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
    )


def bound_installation() -> OnDemandInstallation:
    services = json.loads(old_receipt().removeprefix(pair._PREFIX))["services"]
    controller, worker = services
    return OnDemandInstallation(
        installed.FAILED_ATTEMPT,
        installed.SOURCE_SHA,
        CONTROLLER_ID,
        controller["image_ref"],
        WORKER_ID,
        worker["image_ref"],
        binding.CANONICAL_DATABASE,
        ReviewedInstalledPair(
            original_browser_attempt=installed.FAILED_ATTEMPT,
            controller_config_hash=controller["config_hash"],
            worker_config_hash=worker["config_hash"],
        ),
    )


def retained_io() -> RetainedIO:
    io = RetainedIO()
    containers = (
        replace(io.value.containers[0], image_id=CTRL_IMAGE_ID),
        replace(io.value.containers[1], image_id=WORKER_IMAGE_ID),
    )
    images = (
        replace(io.value.images[0], ident=CTRL_IMAGE_ID),
        replace(io.value.images[1], ident=WORKER_IMAGE_ID),
    )
    io.value = replace(
        io.value,
        containers=containers,
        images=images,
        global_image_ids=frozenset(image.ident for image in images),
    )
    return io


@pytest.fixture
def lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    lease_dir = tmp_path / "lease"
    lease_dir.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_dir)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    with cleanup.protected_boca_job_lease(NEW_RUN) as held:
        yield held


def adapter(
    *,
    old: bytes | None = None,
    retained: adapters.CustodyEvidence | None = None,
    io: RetainedIO | None = None,
    pair_reader: Any = None,
    binding_reader: Any = None,
    identity_reader: Any = None,
) -> capture.ProductionSameLeaseCapture:
    return capture.ProductionSameLeaseCapture(
        observation_receipt=old_receipt() if old is None else old,
        custody=_CUSTODY if retained is None else retained,
        retained_io=retained_io() if io is None else io,
        pair_reader=(lambda _run: old_receipt(NEW_RUN)) if pair_reader is None else pair_reader,
        binding_reader=(lambda _lease: bound_installation())
        if binding_reader is None
        else binding_reader,
        control_identity_reader=(lambda _name: "3" * 64)
        if identity_reader is None
        else identity_reader,
    )


def test_capture_reconciles_historical_artifact_and_live_double_census_under_one_lease(
    lease: cleanup.BocaJobLease,
) -> None:
    reads: list[tuple[str, object]] = []

    def fresh(run: str) -> bytes:
        reads.append(("pair", run))
        return old_receipt(NEW_RUN)

    def service(current: cleanup.BocaJobLease) -> OnDemandInstallation:
        reads.append(("binding", current))
        return bound_installation()

    def inode(name: str) -> str:
        reads.append(("inode", name))
        return "3" * 64

    result = adapter(pair_reader=fresh, binding_reader=service, identity_reader=inode)(
        plan(), lease
    )
    assert result.observation_run_id == OLD_RUN  # Historical authenticated artifact.
    assert result.old_source_sha == installed.SOURCE_SHA
    assert result.controller_id == CONTROLLER_ID
    assert result.worker_id == WORKER_ID
    assert result.retained == _CUSTODY.resources
    assert result.control_inode_sha256 == "3" * 64
    assert reads == [
        ("pair", NEW_RUN),
        ("binding", lease),
        ("binding", lease),
        ("inode", "control_socket_directory"),
        ("inode", "control_socket_directory"),
        ("pair", NEW_RUN),
    ]
    result.validate(plan(), _CUSTODY.resources)


def test_successor_journal_calls_capture_twice_under_the_same_held_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lease: cleanup.BocaJobLease,
) -> None:
    root = tmp_path / "stage"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    count = 0
    real_capture = adapter()

    def same_lease(
        current: transaction.PairCoordinates, held: cleanup.BocaJobLease
    ) -> journal.FreshPairWitness:
        nonlocal count
        assert held is lease
        count += 1
        return real_capture(current, held)

    record = journal.SuccessorPairJournal(
        adapters.ReleaseEvidence(
            "a" * 40,
            RELEASE_RUN,
            plan().controller_ref,
            plan().worker_ref,
            "6" * 64,
            "7" * 64,
        ),
        _CUSTODY.resources,
        same_lease,
    )
    record.intent(plan(), lease)
    assert count == 2
    evidence = root / f".boca-pair-upgrade-{NEW_RUN}.evidence"
    intent = root / f".boca-pair-upgrade-{NEW_RUN}.intent"
    assert evidence.is_file() and intent.is_file()
    assert json.loads(evidence.read_bytes())["witness"]["control_inode_sha256"] == "3" * 64
    assert b"TOKEN" not in evidence.read_bytes()


@pytest.mark.parametrize(
    "change",
    (
        "pair-source",
        "pair-image",
        "worker-exit",
        "worker-exited",
        "controller-unhealthy",
        "binding",
        "control-inode",
        "retained-ipc-inode",
        "retained-image",
        "retained-creator",
        "pair-drift",
        "binding-drift",
        "control-drift",
    ),
)
def test_any_physical_mismatch_fails_closed_without_secret_detail(
    lease: cleanup.BocaJobLease, change: str
) -> None:
    current = plan()
    io = retained_io()
    physical = json.loads(old_receipt(NEW_RUN).removeprefix(pair._PREFIX))
    installation = bound_installation()
    identity = ["3" * 64, "3" * 64]
    pair_reads: list[bytes] = []
    binding_reads: list[OnDemandInstallation] = []
    if change == "pair-source":
        physical["source_sha"] = "9" * 40
    if change == "pair-image":
        physical["services"][0]["image_id"] = "sha256:" + "9" * 64
    if change == "worker-exit":
        physical["services"][1]["exit_code"] = 1
    if change == "worker-exited":
        physical["services"][1]["status"] = "exited"
    if change == "controller-unhealthy":
        physical["services"][0]["health"] = "unhealthy"
    if change == "binding":
        installation = replace(installation, worker_id="f" * 64)
    if change == "control-inode":
        identity = ["9" * 64, "9" * 64]
    if change == "retained-ipc-inode":
        io.identities["boca-socios_boca_browser_ipc"] = "9" * 64
    if change == "retained-image":
        io.value = replace(
            io.value,
            containers=(replace(io.value.containers[0], image_id="sha256:" + "9" * 64),)
            + io.value.containers[1:],
        )
    if change == "retained-creator":
        io.value = replace(
            io.value,
            volumes=(
                replace(
                    io.value.volumes[0],
                    labels=tuple(
                        (key, "44000000011" if key == "boca.socios.browser-ipc-attempt" else val)
                        for key, val in io.value.volumes[0].labels
                    ),
                ),
            )
            + io.value.volumes[1:],
        )
    raw = pair._canonical(physical)
    pair_reads = [raw, raw]
    binding_reads = [installation, installation]
    if change == "pair-drift":
        pair_reads[1] = old_receipt(NEW_RUN)
        pair_reads[0] = pair._canonical({**physical, "source_sha": "8" * 40})
    if change == "binding-drift":
        binding_reads[1] = replace(installation, worker_id="f" * 64)
    if change == "control-drift":
        identity[1] = "9" * 64
    witness = adapter(
        io=io,
        pair_reader=lambda _: pair_reads.pop(0),
        binding_reader=lambda _: binding_reads.pop(0),
        identity_reader=lambda _: identity.pop(0),
    )
    with pytest.raises(capture.SameLeaseCaptureNoGo, match="same-lease evidence unverified"):
        witness(current, lease)


def test_missing_custody_is_no_go_before_any_host_read(lease: cleanup.BocaJobLease) -> None:
    called: list[str] = []
    instance = capture.ProductionSameLeaseCapture(
        observation_receipt=old_receipt(),
        custody=None,
        retained_io=retained_io(),
        pair_reader=lambda _: called.append("pair") or old_receipt(NEW_RUN),
        binding_reader=lambda _: called.append("binding") or bound_installation(),
        control_identity_reader=lambda _: called.append("inode") or "3" * 64,
    )
    with pytest.raises(capture.SameLeaseCaptureNoGo):
        instance(plan(), lease)
    assert called == []


def test_fake_or_changed_observation_and_stale_lease_are_no_go(
    lease: cleanup.BocaJobLease,
) -> None:
    forged = json.loads(old_receipt().removeprefix(pair._PREFIX))
    forged["observation_run_id"] = "44000000012"
    with pytest.raises(capture.SameLeaseCaptureNoGo):
        adapter(old=pair._canonical(forged))(plan(), lease)
    with pytest.raises(capture.SameLeaseCaptureNoGo):
        adapter()(replace(plan(), old_source_sha="9" * 40), lease)
    lease.active = False
    with pytest.raises(capture.SameLeaseCaptureNoGo):
        adapter()(plan(), lease)


def test_sensitive_host_exception_is_always_redacted(lease: cleanup.BocaJobLease) -> None:
    with pytest.raises(capture.SameLeaseCaptureNoGo) as failure:
        adapter(pair_reader=lambda _run: (_ for _ in ()).throw(OSError("TOKEN=SECRET")))(
            plan(), lease
        )
    assert "TOKEN=SECRET" not in str(failure.value)


def test_production_resource_io_uses_only_existing_readonly_narrow_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("inspect", "--format"):
            return {
                "{{json .State.Status}}": '"created"',
                "{{json .State.Running}}": "false",
                "{{json .State.Pid}}": "0",
                "{{json .State.ExitCode}}": "0",
                "{{json .Mounts}}": "[]",
            }[args[2]]
        return '"/home/boca-deploy/.local/share/docker"'

    monkeypatch.setattr(capture.cleanup, "_docker", docker)
    monkeypatch.setattr(capture.cleanup, "_rootless_docker_disk_inodes", lambda: (0, 0, 1, 1))
    monkeypatch.setattr(capture.cleanup, "capture_inventory", lambda: "sentinel")
    monkeypatch.setattr(capture.retained, "_identity", lambda _: "1" * 64)
    monkeypatch.setattr(capture.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(capture.os, "getegid", lambda: 10001)
    io = capture.ProductionRetainedResourceIO()
    assert io.rootless_identity() == (
        10001,
        10001,
        "/home/boca-deploy/.local/share/docker",
    )
    assert io.inventory() == "sentinel"
    assert io.identity("boca-socios_boca_browser_ipc") == "1" * 64
    assert io.worker_state("b" * 64) == {
        "Status": "created",
        "Running": False,
        "Pid": 0,
        "ExitCode": 0,
    }
    assert io.mounts("a" * 64) == []
    for forbidden in ("State.Status", "State.Pid", "State.ExitCode"):
        with pytest.raises(cleanup.CleanupError, match="allowlist"):
            cleanup._inspect_field("container", "b" * 64, forbidden)
    assert all("Config.Env" not in str(item) for item in calls)
    assert all(
        item[0] not in {"stop", "rm", "prune", "start", "run", "create"}
        for item in calls
        if isinstance(item, tuple)
    )


def test_authenticated_host_capture_requires_two_canonical_bundled_proofs(
    monkeypatch: pytest.MonkeyPatch, lease: cleanup.BocaJobLease
) -> None:
    with monkeypatch.context() as original_host:
        original_host.setattr(cleanup, "EXPECTED_UID", 10001)
        retained_proof, retained_raw, pair_proof, pair_raw = authenticated_artifacts()
    physical_calls: list[tuple[object, object, object]] = []

    def physical(
        self: capture.ProductionSameLeaseCapture,
        p: transaction.PairCoordinates,
        held: cleanup.BocaJobLease,
    ) -> str:
        physical_calls.append((self, p, held))
        return "physical-capture-invoked"

    monkeypatch.setattr(capture.ProductionSameLeaseCapture, "__call__", physical)
    current = replace(plan(), observation_run_id=AUTH_PAIR_RUN, release_run_id=AUTH_RELEASE_RUN)
    bridge = capture.AuthenticatedProductionSameLeaseCapture(
        AUTH_MAIN,
        AUTH_RETAINED_RUN,
        pair_proof,
        pair_raw,
        retained_proof,
        retained_raw,
    )
    assert bridge(current, lease) == "physical-capture-invoked"
    assert len(physical_calls) == 1
    physical_reader, observed_plan, observed_lease = physical_calls[0]
    assert observed_plan is current and observed_lease is lease
    assert isinstance(physical_reader, capture.ProductionSameLeaseCapture)
    assert physical_reader.observation_receipt == pair_raw
    assert physical_reader.custody is not None
    assert physical_reader.custody.observation_run_id == AUTH_RETAINED_RUN
    assert isinstance(physical_reader.retained_io, capture.ProductionRetainedResourceIO)
    assert physical_reader.pair_reader is pair.observe
    assert physical_reader.binding_reader is capture.service.read_installed_binding
    assert physical_reader.control_identity_reader is capture.retained._identity


def test_authenticated_capture_never_reaches_physical_readers_with_bad_proof(
    monkeypatch: pytest.MonkeyPatch, lease: cleanup.BocaJobLease
) -> None:
    with monkeypatch.context() as original_host:
        original_host.setattr(cleanup, "EXPECTED_UID", 10001)
        retained_proof, retained_raw, pair_proof, pair_raw = authenticated_artifacts()
    monkeypatch.setattr(
        capture.ProductionSameLeaseCapture,
        "__call__",
        lambda *_args: pytest.fail("untrusted artifact reached live host I/O"),
    )
    current = replace(plan(), observation_run_id=AUTH_PAIR_RUN, release_run_id=AUTH_RELEASE_RUN)
    for pair_bytes, retained_bytes, claimed_source in (
        (pair_proof + b"{}", retained_proof, AUTH_MAIN),
        (pair_proof, retained_proof + b"{}", AUTH_MAIN),
        (pair_proof, retained_proof, "f" * 40),
    ):
        bridge = capture.AuthenticatedProductionSameLeaseCapture(
            claimed_source,
            AUTH_RETAINED_RUN,
            pair_bytes,
            pair_raw,
            retained_bytes,
            retained_raw,
        )
        with pytest.raises(capture.SameLeaseCaptureNoGo):
            bridge(current, lease)
