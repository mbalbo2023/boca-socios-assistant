"""Real adapter against disposable fake Docker and private staged filesystem.

No host SSH, Docker daemon, live site, tokens, blackbox execution, buying or
reservation. These prove orchestration, not physical production acceptance.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover as cutover
from boca_socios import host_boca_cutover_backend as adapter
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios import host_cutover_ipc_probe as ipc_probe
from boca_socios import host_cutover_stage as stage

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "compose.beta.yaml").read_bytes()
REVIEWED_OVERLAY = (ROOT / "compose.beta.browser.yaml").read_bytes()
# These archived protocol fixtures predate the opt-in cold profile.
OVERLAY = b"services:\n  controller:\n    environment:\n      BOCA_BROWSER_BACKEND: ipc\n"
SECCOMP = (ROOT / "docker/seccomp_profile.json").read_bytes()
SQL = b"fake reviewed SQL (never executed)"
LEGACY = b"services:\n  controller:\n    image: frozen-legacy\n"
REAL_COMPOSE_HASH = adapter._reviewed_compose_hash
REAL_LEGACY_DISK_ID = adapter._legacy_disk_identity
OLD = "1" * 64
WORKER = "2" * 64
NEW = "3" * 64
OLD_IMAGE_ID = "sha256:" + "f" * 64
SHA = lambda value: hashlib.sha256(value).hexdigest()  # noqa: E731 - fixture shorthand


def test_authenticated_option_b_memfd_zip_extracts_four_reviewed_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The source ZIP has five entries, but the adapter is a four-field record.

    Exercise the real memfd path: synthetic adapter fixtures had hidden a
    positional-constructor crash before Cutover A could attest the host.
    """
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import build_protected_boca_bundle as builder

    package = tmp_path / "reviewed.pyz"
    builder.build(ROOT, package)
    fd = os.memfd_create("boca-cutover-zip-test", flags=0)
    try:
        os.write(fd, package.read_bytes())
        monkeypatch.setattr(sys, "argv", [f"/proc/self/fd/{fd}"])
        source = adapter.ReviewedCutoverSources.from_verified_zip()
    finally:
        os.close(fd)
    assert source.base == BASE
    assert source.overlay == REVIEWED_OVERLAY
    assert source.seccomp == SECCOMP
    assert (
        source.session_sql
        == (
            ROOT / "src/boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql"
        ).read_bytes()
    )


def _plan() -> cutover.CutoverPlan:
    return cutover.CutoverPlan(
        attempt_id="41949228860",
        legacy_id=OLD,
        legacy_sha="a" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        legacy_compose_sha=SHA(LEGACY),
        target_sha="c" * 40,
        target_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,
        target_compose_sha=SHA(BASE),
        overlay_sha=SHA(OVERLAY),
        seccomp_sha=SHA(SECCOMP),
        owner_subject="owner",
    )


@pytest.fixture
def fake_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[list[str], Path]:
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(stage, "ROOT", tmp_path / "boca-socios")
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    (stage.ROOT).mkdir(mode=0o700)
    original = stage.ROOT / "compose.beta.yaml"
    original.write_bytes(LEGACY)
    original.chmod(0o600)
    tmp_path.chmod(0o700)
    events: list[str] = []
    original_state = ["RUNNING"]
    worker_state = ["absent"]

    def observe(*_args: object) -> None:
        assert original_state[0] == "RUNNING"
        events.append("attest")

    monkeypatch.setattr(adapter.host, "_cutover_observe", observe)
    monkeypatch.setattr(
        adapter.host, "_browser_compose_model", lambda *_a, **_k: events.append("model")
    )
    monkeypatch.setattr(adapter, "_reviewed_compose_hash", lambda _p, svc, **_kw: SHA(svc.encode()))
    monkeypatch.setattr(
        adapter.host, "_browser_pull_both", lambda *_a, **_kw: events.append("pull")
    )

    def prepare(*_args: object, **_kwargs: object) -> str:
        assert original.read_bytes() == LEGACY
        events.append("worker")
        worker_state[0] = "present"
        return WORKER

    monkeypatch.setattr(adapter.host, "_cutover_prepare_worker", prepare)

    def park(*_args: object) -> None:
        assert original_state[0] == "RUNNING"
        original_state[0] = "PARKED"
        assert original.read_bytes() == LEGACY
        events.append("park")

    monkeypatch.setattr(adapter.host, "_cutover_park_original", park)
    monkeypatch.setattr(
        adapter, "_legacy_disk_identity", lambda _p: (Path("/fake/boca.sqlite3"), (5, 6))
    )

    def activate(*_args: object, **_kwargs: object) -> str:
        assert original_state[0] == "PARKED"
        assert original.read_bytes() == LEGACY
        events.append("candidate")
        return NEW

    monkeypatch.setattr(adapter.host, "_cutover_activate_candidate", activate)
    monkeypatch.setattr(
        adapter.host,
        "_cutover_candidate_postflight",
        lambda *_a, **_kw: events.append("health") or True,
    )

    def verify_peer(candidate_id: str) -> None:
        assert candidate_id == NEW
        events.append("ipc-peer")

    monkeypatch.setattr(ipc_probe, "verify_controller_peer", verify_peer)
    monkeypatch.setattr(
        adapter.host, "_browser_worker_postflight", lambda *_a, **_k: events.append("worker-health")
    )
    monkeypatch.setattr(
        adapter.host, "_beta_loopback_health", lambda *_a: events.append("loopback")
    )
    monkeypatch.setattr(
        adapter.host,
        "_cutover_legacy_record",
        lambda *_a, **_k: {"Image": OLD_IMAGE_ID},
    )
    monkeypatch.setattr(
        adapter,
        "_precommit_legacy_image_cleanup",
        lambda _plan, _legacy, _candidate, _worker: (
            cleanup.LegacyImageProof(OLD_IMAGE_ID, _plan.legacy_image, _plan.legacy_sha),
            None,
        ),
    )

    def retire(*_args: object, **_kw: object) -> None:
        assert original_state[0] == "PARKED"
        assert original.read_bytes() == BASE
        assert (stage.ROOT / "compose.beta.browser.yaml").read_bytes() == OVERLAY
        assert (stage.ROOT / "seccomp_profile.json").read_bytes() == SECCOMP
        original_state[0] = "RETIRED"
        events.append("retire")

    monkeypatch.setattr(adapter.host, "_cutover_retire_accepted_original", retire)

    def inspect(ident: str) -> dict[str, object]:
        assert ident == OLD
        return {
            "Name": (
                "/boca-socios-controller-1"
                if original_state[0] == "RUNNING"
                else f"/boca-socios-controller-legacy-{_plan().attempt_id}"
            ),
        }

    monkeypatch.setattr(adapter.host, "_browser_inspect_record", inspect)
    monkeypatch.setattr(
        adapter.host,
        "_cutover_worker_name_id",
        lambda: WORKER if worker_state[0] == "present" else None,
    )

    def recover(*_args: object, **_kw: object) -> None:
        assert original_state[0] == "PARKED"
        original_state[0] = "RUNNING"
        events.append("recover-original")

    monkeypatch.setattr(adapter.host, "_cutover_compensate_candidate", recover)

    def recover_worker(*_args: object) -> None:
        assert worker_state[0] == "present"
        worker_state[0] = "absent"
        events.append("recover-worker")

    monkeypatch.setattr(adapter.host, "_cutover_compensate_worker", recover_worker)

    def clean(
        outcome: str,
        attempt_id: str,
        *,
        preserve_containers: frozenset[str],
        lease: cleanup.BocaJobLease,
        **_kwargs: object,
    ) -> cleanup.CleanupReceipt:
        cleanup.verify_protected_boca_job_lease(lease, attempt_id)
        assert preserve_containers == (
            frozenset({NEW, WORKER}) if outcome == "SUCCESS" else frozenset({OLD})
        )
        if outcome == "SUCCESS":
            proof = _kwargs.get("historical_legacy")
            assert isinstance(proof, cleanup.LegacyImageProof)
            assert proof.ident == OLD_IMAGE_ID
        else:
            assert _kwargs.get("historical_legacy") is None
        events.append("cleanup")
        disk = cleanup.DiskInodes(1000, 100, 3000, 300, 8, 10, 16, 18)
        return cleanup.CleanupReceipt(outcome, attempt_id, "ACCEPT", disk, disk, (), (), ())

    monkeypatch.setattr(adapter.cleanup, "execute_protected", clean)
    monkeypatch.setattr(
        adapter.cleanup,
        "capture_inventory",
        lambda **_kw: cleanup.Inventory(
            (), (), (), (), cleanup.DiskInodes(1000, 100, 3000, 300, 8, 10, 16, 18)
        ),
    )
    monkeypatch.setattr(adapter, "_SQL_SHA", SHA(SQL))
    return events, stage.ROOT


def _backend(events: list[str]) -> adapter.RootlessCutoverBackend:
    def bootstrap(
        path: Path,
        *,
        held_lease_fd: int,
        expected_db_identity: tuple[int, int],
        session_schema_bytes: bytes,
    ) -> str:
        assert path == Path("/fake/boca.sqlite3")
        assert expected_db_identity == (5, 6)
        assert session_schema_bytes == SQL
        assert held_lease_fd >= 0
        events.append("bootstrap")
        return "APPLIED"

    return adapter.RootlessCutoverBackend(
        adapter.ReviewedCutoverSources(BASE, OVERLAY, SECCOMP, SQL),
        session_bootstrap=bootstrap,
    )


def _run_adapter(backend: adapter.RootlessCutoverBackend) -> cutover.CutoverReceipt:
    """Injected fake receipt callbacks; real persistence tested independently."""
    phases: list[str] = []

    def fake_preflight(plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        phases.append("preflight-before-docker")

    def fake_sink(
        plan: cutover.CutoverPlan,
        _receipt: cutover.CutoverReceipt,
        lease: cleanup.BocaJobLease,
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        phases.append("sink-after-finalizer")

    result = cutover.run_cutover_a(
        _plan(), backend=backend, terminal_preflight=fake_preflight, terminal_sink=fake_sink
    )
    assert phases == ["preflight-before-docker", "sink-after-finalizer"]
    return result


def test_full_host_adapter_uses_real_stage_promotion_and_cleanup(
    fake_host: tuple[list[str], Path],
) -> None:
    events, root = fake_host
    receipt = _run_adapter(_backend(events))
    assert receipt.accepted and receipt.cleanup_receipt is not None
    assert receipt.cleanup_receipt.redacted_json() and receipt.state == "ACCEPTED"
    assert events == [
        "attest",
        "model",
        "pull",
        "worker",
        "park",
        "bootstrap",
        "candidate",
        "health",
        "ipc-peer",
        "worker-health",
        "loopback",
        "retire",
        "cleanup",
    ]
    assert set(path.name for path in root.iterdir()) == {
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "seccomp_profile.json",
    }
    assert (root / "compose.beta.yaml").read_bytes() == BASE


def test_unverified_controller_peer_blocks_retirement_and_recovers_original(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, root = fake_host

    def peer_unverified(candidate_id: str) -> None:
        assert candidate_id == NEW
        raise adapter.host.PreflightError("private transport details")

    monkeypatch.setattr(ipc_probe, "verify_controller_peer", peer_unverified)
    receipt = _run_adapter(_backend(events))
    assert receipt.failed_phase == "ACCEPT_CANDIDATE"
    assert receipt.original_restored and not receipt.irreversible_commit_started
    assert not receipt.accepted and "retire" not in events
    assert events[-3:] == ["recover-original", "recover-worker", "cleanup"]
    assert (root / "compose.beta.yaml").read_bytes() == LEGACY


def test_future_host_hook_sequences_durable_intent_and_result_under_one_lease(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, _ = fake_host
    source = adapter.ReviewedCutoverSources(BASE, OVERLAY, SECCOMP, SQL)
    bootstrap = _backend(events).session_bootstrap
    assert bootstrap is not None
    monkeypatch.setattr(
        adapter.ReviewedCutoverSources,
        "from_verified_zip",
        classmethod(lambda _cls: source),
    )
    monkeypatch.setattr(adapter, "_stdlib_session_bootstrap", lambda: bootstrap)

    def preflight(plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> str:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        assert events == []
        events.append("persistent-intent")
        return "1" * 64

    def write(
        record: terminal.TerminalRecord,
        *,
        plan: cutover.CutoverPlan,
        lease: cleanup.BocaJobLease,
    ) -> str:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        assert record.state == "ACCEPTED" and record.cleanup == "ACCEPT"
        assert events[-1] == "cleanup"
        events.append("persistent-result")
        return "2" * 64

    monkeypatch.setattr(terminal, "prepare_destination", preflight)
    monkeypatch.setattr(terminal, "write_once", write)
    receipt = adapter.execute_reviewed_cutover(_plan())
    assert receipt.accepted
    assert events[0] == "persistent-intent"
    assert events[-2:] == ["cleanup", "persistent-result"]


def test_future_host_hook_refuses_untrusted_sql_before_intent_or_docker(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, _ = fake_host
    source = adapter.ReviewedCutoverSources(BASE, OVERLAY, SECCOMP, b"not approved SQL")
    monkeypatch.setattr(
        adapter.ReviewedCutoverSources,
        "from_verified_zip",
        classmethod(lambda _cls: source),
    )
    with pytest.raises(cutover.CutoverError, match="reviewed Compose/seccomp/Option B"):
        adapter.execute_reviewed_cutover(_plan())
    assert events == []


def test_no_go_on_option_b_missing_sql_before_any_host_call(
    fake_host: tuple[list[str], Path],
) -> None:
    events, root = fake_host
    backend = _backend(events)
    backend.sources = replace(backend.sources, session_sql=b"untrusted")
    receipt = _run_adapter(backend)
    assert receipt.state == "NO_GO" and not receipt.accepted
    assert not events
    assert (root / "compose.beta.yaml").read_bytes() == LEGACY


@pytest.mark.parametrize("primary", ["STORAGE", "PULL"])
def test_worker_prepare_preserves_dual_pull_subphase_without_private_error(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch, primary: str
) -> None:
    events, _root = fake_host

    def interrupted_pull(*_args: object, phase_hook: object = None) -> None:
        if callable(phase_hook):
            phase_hook(primary)
        raise adapter.host.PreflightError("private Docker storage content")

    monkeypatch.setattr(adapter.host, "_browser_pull_both", interrupted_pull)
    backend = _backend(events)
    plan = _plan()
    with cleanup.protected_boca_job_lease(plan.attempt_id) as lease:
        backend.attest_original(plan, lease)
        backend.stage(plan, lease)
        with pytest.raises(adapter.host.CutoverWorkerPhaseError) as captured:
            backend.prepare_worker(plan, lease)
    assert captured.value.primary == primary
    assert captured.value.compensation == "UNVERIFIED"
    assert "private Docker" not in str(captured.value)


def test_option_b_failure_compensates_exact_old_id_and_removes_stage(
    fake_host: tuple[list[str], Path],
) -> None:
    events, root = fake_host

    def bad_bootstrap(*_args: object, **_kwargs: object) -> str:
        events.append("bootstrap-failed")
        raise cutover.CutoverError("synthetic DB mismatch")

    backend = _backend(events)
    backend.session_bootstrap = bad_bootstrap
    receipt = _run_adapter(backend)
    assert receipt.state == "RECOVERED" and receipt.original_restored
    assert not receipt.accepted
    assert "candidate" not in events
    assert events[-3:] == ["recover-original", "recover-worker", "cleanup"]
    assert set(path.name for path in root.iterdir()) == {"compose.beta.yaml"}
    assert (root / "compose.beta.yaml").read_bytes() == LEGACY


def test_lost_compose_promotion_receipt_blocks_rollback_and_leaves_intent(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, root = fake_host
    real_replace = stage.os.replace
    count = [0]

    def partial(*args: object, **kwargs: object) -> None:
        count[0] += 1
        if count[0] == 2:
            raise OSError("simulated source promotion loss")
        real_replace(*args, **kwargs)

    monkeypatch.setattr(stage.os, "replace", partial)
    receipt = _run_adapter(_backend(events))
    assert receipt.state == "NO_GO" and receipt.irreversible_commit_started
    assert "recover-original" not in events
    assert "retire" not in events
    assert (root / "compose.beta.yaml").read_bytes() == BASE
    assert (root / f"cutover-a-{_plan().attempt_id}" / stage.COMMIT_INTENT).exists()


def test_unknown_retirement_never_deletes_candidate_worker_or_restarts_legacy(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, root = fake_host

    def lost_retirement(*_args: object, **_kw: object) -> None:
        # Assume Docker DID remove the old exact ID before its return was lost.
        events.append("legacy-rm-effect-unknown")
        raise cutover.CutoverError("lost Docker rm receipt after effect")

    def must_not_delete(*_args: object, **_kwargs: object) -> None:
        pytest.fail("uncertain cutover may not invoke deletion planner")

    def read_only() -> SimpleNamespace:
        events.append("readonly-census")
        return SimpleNamespace()

    monkeypatch.setattr(adapter.host, "_cutover_retire_accepted_original", lost_retirement)
    monkeypatch.setattr(adapter.cleanup, "execute_protected", must_not_delete)
    monkeypatch.setattr(adapter.cleanup, "capture_inventory", read_only)
    receipt = _run_adapter(_backend(events))
    assert receipt.state == "NO_GO" and receipt.irreversible_commit_started
    assert not receipt.original_restored and not receipt.accepted
    assert "readonly-census" in events
    assert "recover-original" not in events
    assert "recover-worker" not in events
    assert (root / "compose.beta.yaml").read_bytes() == BASE
    assert (root / f"cutover-a-{_plan().attempt_id}" / stage.COMMIT_INTENT).exists()


def test_failed_precommit_recovery_never_cleans_parked_or_live_worker(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    events, root = fake_host

    def failed_bootstrap(*_args: object, **_kwargs: object) -> str:
        events.append("bootstrap-failed")
        raise cutover.CutoverError("host session unavailable")

    def failed_recovery(*_args: object, **_kw: object) -> None:
        events.append("recover-unknown")
        raise cutover.CutoverError("original ID remains parked; restart receipt lost")

    def must_not_delete(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unrestored original must not allow worker deletion")

    def read_only() -> SimpleNamespace:
        events.append("readonly-census")
        return SimpleNamespace()

    backend = _backend(events)
    backend.session_bootstrap = failed_bootstrap
    monkeypatch.setattr(adapter.host, "_cutover_compensate_candidate", failed_recovery)
    monkeypatch.setattr(adapter.cleanup, "execute_protected", must_not_delete)
    monkeypatch.setattr(adapter.cleanup, "capture_inventory", read_only)
    receipt = _run_adapter(backend)
    assert receipt.state == "NO_GO" and not receipt.original_restored
    assert not receipt.irreversible_commit_started
    assert "recover-unknown" in events and "readonly-census" in events
    assert "recover-worker" not in events and "cleanup" not in events
    assert (root / "compose.beta.yaml").read_bytes() == LEGACY
    assert (root / f"cutover-a-{_plan().attempt_id}").exists()


@pytest.mark.parametrize("output", ["hash-only", "service-prefix", "foreign", "multiple"])
def test_host_compose_service_hash_is_derived_from_verified_staged_model(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    _events, _root = fake_host
    monkeypatch.setattr(adapter, "_reviewed_compose_hash", REAL_COMPOSE_HASH)
    plan = _plan()
    stage.initialize(
        plan.attempt_id,
        plan.legacy_id,
        plan.legacy_sha,
        plan.legacy_compose_sha,
        plan.target_sha,
        plan.target_image,
        plan.browser_image,
        plan.target_compose_sha,
        plan.overlay_sha,
        plan.seccomp_sha,
    )
    for slot, data, sha in (
        ("base", BASE, plan.target_compose_sha),
        ("overlay", OVERLAY, plan.overlay_sha),
        ("seccomp", SECCOMP, plan.seccomp_sha),
    ):
        stage.upload(slot, sha, plan.attempt_id, plan.legacy_compose_sha, io.BytesIO(data))

    def config(*args: str, **kwargs: object) -> str:
        assert args[0:4] == ("docker", "compose", "-p", "boca-socios")
        assert "--hash" in args and args[-1] == "controller"
        assert f"cutover-a-{plan.attempt_id}" in args[5]
        assert kwargs["env"]["BOCA_BROWSER_IMAGE"] == plan.browser_image  # type: ignore[index]
        return {
            "hash-only": "a" * 64,
            "service-prefix": "controller " + "a" * 64,
            "foreign": "other " + "a" * 64,
            "multiple": "a" * 64 + "\n" + "b" * 64,
        }[output]

    monkeypatch.setattr(adapter.host, "_run", config)
    if output in ("hash-only", "service-prefix"):
        assert adapter._reviewed_compose_hash(plan, "controller") == "a" * 64
    else:
        with pytest.raises(cutover.CutoverError, match="hash uncertain"):
            adapter._reviewed_compose_hash(plan, "controller")


@pytest.mark.parametrize("db_drift", ["none", "shared", "controller", "link"])
def test_host_data_volume_attestor_requires_stopped_single_owner_only(
    fake_host: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch, db_drift: str
) -> None:
    _events, root = fake_host
    monkeypatch.setattr(adapter, "_legacy_disk_identity", REAL_LEGACY_DISK_ID)
    plan = _plan()
    docker_root = root / "rootless-docker"
    directory = docker_root / "volumes" / adapter.host.DATA_VOLUME / "_data"
    directory.mkdir(parents=True)
    db = directory / "boca.sqlite3"
    db.write_bytes(b"fake-boca-legacy-db-is-never-opened")
    db.chmod(0o600)
    monkeypatch.setattr(adapter.host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(adapter.host, "_validate_data_volume", lambda: None)
    monkeypatch.setattr(adapter.host, "_checked_docker_storage_dir", lambda: docker_root)
    monkeypatch.setattr(adapter.host, "_cutover_legacy_record", lambda *_a, **_k: {})
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        metadata = original_lstat(path)
        if path == db and db_drift != "link":
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=10001,
                st_gid=10001,
                st_nlink=1,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    def ps(*args: str, **_kwargs: object) -> str:
        assert args[0:3] == ("docker", "ps", "-a")
        if any(arg.startswith("volume=") for arg in args):
            return OLD if db_drift != "shared" else OLD + "\n" + NEW
        return OLD if db_drift != "controller" else OLD + "\n" + NEW

    monkeypatch.setattr(adapter.host, "_run", ps)
    if db_drift == "link":
        db.unlink()
        db.symlink_to(root / "non-boca")
    if db_drift == "none":
        path, identity = adapter._legacy_disk_identity(plan)
        assert path == db and identity == (db.stat().st_dev, db.stat().st_ino)
    else:
        with pytest.raises((cutover.CutoverError, OSError)):
            adapter._legacy_disk_identity(plan)


def test_prepared_cutover_backend_aborts_on_missing_durable_marker(
    fake_host: tuple[list[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, _ = fake_host
    source = adapter.ReviewedCutoverSources(BASE, OVERLAY, SECCOMP, SQL)
    bootstrap = _backend(events).session_bootstrap
    assert bootstrap is not None
    monkeypatch.setattr(
        adapter.ReviewedCutoverSources,
        "from_verified_zip",
        classmethod(lambda _cls: source),
    )
    monkeypatch.setattr(adapter, "_stdlib_session_bootstrap", lambda: bootstrap)
    monkeypatch.setattr(terminal, "prepare_destination", lambda *_a: events.append("intent"))
    monkeypatch.setattr(terminal, "write_once", lambda *_a, **_k: events.append("terminal"))
    monkeypatch.setattr(
        adapter.host, "_validate_docker_boundary", lambda: events.append("rootless")
    )
    monkeypatch.setattr(adapter.host, "_validate_data_volume", lambda: events.append("volume"))

    def failed_exec(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "exec"):
            events.append("marker-uncertain")
            raise adapter.CutoverError("marker not durably recorded")
        raise AssertionError("unexpected host call")

    monkeypatch.setattr(adapter.host, "_run", failed_exec)
    result = adapter.execute_reviewed_cutover(_plan(), prepare_run_id="50000000001")
    assert not result.accepted
    assert events[:5] == ["intent", "attest", "rootless", "volume", "marker-uncertain"]
    assert "pull" not in events and "park" not in events


def _precommit_inventory(
    *,
    extra_unknown: bool = False,
    exact_historical: bool = False,
) -> cleanup.Inventory:
    """Three exact Boca CIDs; only the old image has authenticated exception."""
    plan = _plan()
    new_image = "sha256:" + "7" * 64
    worker_image = "sha256:" + "8" * 64
    images = (
        cleanup.Image(
            OLD_IMAGE_ID,
            (plan.legacy_image,),
            None,
            historical_legacy_attested=True,
        ),
        cleanup.Image(new_image, (plan.target_image,), None),
        cleanup.Image(worker_image, (plan.browser_image,), None),
    )
    if extra_unknown:
        images += (
            cleanup.Image(
                "sha256:" + "9" * 64,
                ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",),
                None,
            ),
        )
    if exact_historical:
        images += (
            cleanup.Image(
                cleanup.HISTORICAL_RETIRE_TARGET,
                ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",),
                None,
            ),
        )
    return cleanup.Inventory(
        containers=(
            cleanup.Container(
                OLD,
                f"/boca-socios-controller-legacy-{plan.attempt_id}",
                OLD_IMAGE_ID,
                False,
                (("com.docker.compose.project", "boca-socios"),),
            ),
            cleanup.Container(
                NEW,
                "/boca-socios-controller-1",
                new_image,
                True,
                (("com.docker.compose.project", "boca-socios"),),
            ),
            cleanup.Container(
                WORKER,
                "/boca-socios-browser-worker-1",
                worker_image,
                True,
                (("com.docker.compose.project", "boca-socios"),),
            ),
        ),
        images=images,
        networks=(),
        volumes=(),
        disk=cleanup.DiskInodes(12_000, 120),
    )


def test_precommit_exact_old_image_proof_allows_only_known_boca_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    proof = cleanup.LegacyImageProof(OLD_IMAGE_ID, plan.legacy_image, plan.legacy_sha)
    calls: list[tuple[str, object]] = []

    def attest(ident: str, reference: str, revision: str) -> cleanup.LegacyImageProof:
        calls.append(("attest", ident))
        assert (ident, reference, revision) == (
            OLD_IMAGE_ID,
            plan.legacy_image,
            plan.legacy_sha,
        )
        return proof

    def probe(*, historical_legacy: cleanup.LegacyImageProof) -> cleanup.Inventory:
        calls.append(("inventory", historical_legacy.ident))
        assert historical_legacy == proof
        return _precommit_inventory()

    monkeypatch.setattr(adapter.cleanup, "attest_historical_legacy_image", attest)
    monkeypatch.setattr(adapter.cleanup, "capture_inventory", probe)
    monkeypatch.setattr(
        adapter.cleanup,
        "delete_exact",
        lambda _target: pytest.fail("precommit cleanup must be read-only"),
    )
    assert adapter._precommit_legacy_image_cleanup(plan, {"Image": OLD_IMAGE_ID}, NEW, WORKER) == (
        proof,
        None,
    )
    assert calls == [("attest", OLD_IMAGE_ID), ("inventory", OLD_IMAGE_ID)]


def test_precommit_verifies_one_historical_image_and_still_rejects_other_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    legacy = cleanup.LegacyImageProof(OLD_IMAGE_ID, plan.legacy_image, plan.legacy_sha)
    historical = cleanup.HistoricalRetainedImageProof(
        cleanup.HISTORICAL_RETIRE_TARGET,
        cleanup.HISTORICAL_RETIRE_DIGEST,
        cleanup.HISTORICAL_RETIRE_REVISION,
    )
    source = _precommit_inventory(exact_historical=True)
    observed: list[str] = []
    monkeypatch.setattr(adapter.cleanup, "attest_historical_legacy_image", lambda *_a: legacy)
    monkeypatch.setattr(adapter.cleanup, "capture_inventory", lambda *, historical_legacy: source)

    def attest(snapshot: cleanup.Inventory) -> cleanup.HistoricalRetainedImageProof:
        assert snapshot is source
        observed.append("history")
        return historical

    monkeypatch.setattr(adapter.cleanup, "attest_historical_retained_image", attest)
    assert adapter._precommit_legacy_image_cleanup(plan, {"Image": OLD_IMAGE_ID}, NEW, WORKER) == (
        legacy,
        historical,
    )
    assert observed == ["history"]

    different = _precommit_inventory(exact_historical=True, extra_unknown=True)
    monkeypatch.setattr(
        adapter.cleanup, "capture_inventory", lambda *, historical_legacy: different
    )
    monkeypatch.setattr(
        adapter.cleanup, "attest_historical_retained_image", lambda _snapshot: historical
    )
    with pytest.raises(cutover.CutoverError, match="precommit"):
        adapter._precommit_legacy_image_cleanup(plan, {"Image": OLD_IMAGE_ID}, NEW, WORKER)


@pytest.mark.parametrize("failure", ["other-unverified", "unknown-legacy-id", "missing-image"])
def test_precommit_cleanup_blocks_irreversible_retirement_if_proof_unknown(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    plan = _plan()
    proof = cleanup.LegacyImageProof(OLD_IMAGE_ID, plan.legacy_image, plan.legacy_sha)
    monkeypatch.setattr(
        adapter.cleanup,
        "attest_historical_legacy_image",
        lambda *_a: proof,
    )
    inventory = _precommit_inventory(extra_unknown=failure == "other-unverified")
    if failure == "missing-image":
        inventory = replace(
            inventory,
            images=tuple(image for image in inventory.images if image.ident != OLD_IMAGE_ID),
        )
    monkeypatch.setattr(
        adapter.cleanup,
        "capture_inventory",
        lambda *, historical_legacy: inventory,
    )
    with pytest.raises(cutover.CutoverError, match="precommit|historical"):
        adapter._precommit_legacy_image_cleanup(
            plan,
            {"Image": "invalid"} if failure == "unknown-legacy-id" else {"Image": OLD_IMAGE_ID},
            NEW,
            WORKER,
        )


def test_idle_profile_requires_authenticated_v3_before_host_calls(monkeypatch):
    sources = adapter.ReviewedCutoverSources(
        BASE,
        b"services:\n  controller:\n    environment:\n      BOCA_BOT_CONTROL: on-demand\n",
        SECCOMP,
        SQL,
    )
    plan = replace(_plan(), overlay_sha=SHA(sources.overlay))
    monkeypatch.setattr(adapter.ReviewedCutoverSources, "from_verified_zip", lambda: sources)
    monkeypatch.setattr(adapter, "_SQL_SHA", SHA(SQL))
    monkeypatch.setattr(adapter, "run_cutover_a", lambda *_a, **_k: pytest.fail("host"))
    with pytest.raises(cutover.CutoverError, match="V3"):
        adapter.execute_reviewed_cutover(plan)


@pytest.mark.parametrize("engine", ["STOPPED", "RUNNING"])
def test_idle_install_service_tied_to_verified_cids_before_retirement(
    fake_host, monkeypatch, engine
):
    from boca_socios import host_on_demand_service as control
    from boca_socios.host_lifecycle_rootless_adapter import ProductionRootlessDockerIO
    from boca_socios.integration.engine_socket import EngineReceipt

    events, _ = fake_host
    backend = _backend(events)
    backend.on_demand = True
    plan = _plan()
    path = Path("/home/boca-deploy/.boca-on-demand/socket")
    monkeypatch.setattr(control, "control_directory", lambda: path)
    monkeypatch.setattr(
        control,
        "prepare_control_directory",
        lambda attempt, lease: events.append("directory") or path,
    )
    monkeypatch.setattr(
        adapter.host, "_cutover_idle_worker", lambda *_: events.append("created-pid-zero")
    )
    monkeypatch.setattr(adapter, "_controller_database_identity", lambda _cid: (5, 8))
    monkeypatch.setattr(
        adapter.host, "_cutover_compose_pair", lambda *a, **kw: events.append("compose-pair")
    )
    monkeypatch.setattr(adapter.host, "_run", lambda *a, **kw: "BOCA_LEDGER_READY")
    monkeypatch.setattr(
        adapter, "_verified_data_volume_path", lambda _p: Path("/fake/boca.sqlite3")
    )
    monkeypatch.setattr(
        adapter, "_bootstrap_in_data_namespace", lambda *_: events.append("bootstrap") or "APPLIED"
    )
    monkeypatch.setattr(
        ProductionRootlessDockerIO,
        "engine_request",
        lambda self, cid, op: EngineReceipt(engine, False, 31),
    )
    monkeypatch.setattr(control, "verify_control", lambda *args: events.append("verify-socket"))

    def install(binding, lease):
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        assert (binding.controller_id, binding.worker_id, binding.installation_run_id) == (
            NEW,
            WORKER,
            plan.attempt_id,
        )
        assert binding.database_path == Path("/fake/boca.sqlite3")
        assert binding.pair.controller_config_hash == SHA(b"controller")
        assert binding.pair.worker_config_hash == SHA(b"browser-worker")
        events.append("install-control")

    monkeypatch.setattr(control, "install_control", install)
    monkeypatch.setattr(control, "remove_control", lambda *args: events.append("remove-control"))
    receipt = _run_adapter(backend)
    assert events.index("directory") < events.index("candidate")
    assert "ipc-peer" not in events and "worker-health" not in events
    if engine == "RUNNING":
        assert not receipt.accepted and not backend.idle_installed
        assert "retire" not in events
        assert events.index("remove-control") < events.index("recover-original")
    else:
        assert receipt.accepted and backend.idle_installed
        assert events.index("candidate") < events.index("install-control") < events.index("retire")
        assert "remove-control" not in events and events.count("verify-socket") >= 1
