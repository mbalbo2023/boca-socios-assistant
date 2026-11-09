"""No-host O_EXCL terminal attestation and same-lease persistence tests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover as cutover
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios.host_boca_cutover_backend import ReviewedCutoverSources, RootlessCutoverBackend

ATTEMPT = "41949228860"
OLD = "1" * 64
NEW = "2" * 64
WORKER = "3" * 64
REAL_MOUNT_CHECK = terminal._persistent_mount
REAL_ACCOUNT_HOME = terminal._account_home
ROOT = Path(__file__).resolve().parents[1]


def _plan() -> cutover.CutoverPlan:
    return cutover.CutoverPlan(
        attempt_id=ATTEMPT,
        legacy_id=OLD,
        legacy_sha="a" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        legacy_compose_sha="c" * 64,
        target_sha="d" * 40,
        target_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64,
        browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64,
        target_compose_sha="4" * 64,
        overlay_sha="5" * 64,
        seccomp_sha="6" * 64,
        owner_subject="owner",
    )


def _accepted() -> cutover.CutoverReceipt:
    return cutover.CutoverReceipt(ATTEMPT, "ACCEPTED", "ACCEPT", False, True, NEW, WORKER)


@pytest.fixture(autouse=True)
def _rootless_receipts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(terminal, "_account_home", lambda: tmp_path)
    monkeypatch.setattr(terminal, "_persistent_mount", lambda _path: None)


def test_terminal_result_is_o_excl_fsynced_and_readback_with_same_lease(tmp_path: Path) -> None:
    plan = _plan()
    record = terminal.TerminalRecord.from_receipt(plan, _accepted())
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        digest = terminal.write_once(record, plan=plan, lease=lease)
        marker = tmp_path / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-result-{ATTEMPT}.json"
        raw = marker.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        contents = json.loads(raw)
        assert contents["state"] == "ACCEPTED"
        assert contents["cleanup"] == "ACCEPT"
        assert contents["legacy_id"] == OLD
        assert contents["intent_sha256"] == hashlib.sha256(terminal._intent_bytes(plan)).hexdigest()
        assert contents["candidate_id"] == NEW
        assert contents["worker_id"] == WORKER
        with pytest.raises(terminal.TerminalReceiptError, match="exclusively"):
            terminal.write_once(record, plan=plan, lease=lease)
        assert marker.read_bytes() == raw
    assert terminal.reconcile_persisted(plan) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    terminal.verify_persisted_exact(plan, _accepted())
    with pytest.raises(terminal.TerminalReceiptError, match="differs from original bytes"):
        terminal.verify_persisted_exact(plan, replace(_accepted(), candidate_id="8" * 64))


@pytest.mark.parametrize("primary", ["CREATE", "HEALTH_UNHEALTHY"])
def test_worker_failure_uses_additive_v2_terminal_schema_without_changing_v1(
    tmp_path: Path,
    primary: str,
) -> None:
    old = terminal.TerminalRecord.from_receipt(_plan(), _accepted()).serialized()
    assert json.loads(old)["version"] == terminal.VERSION
    assert "worker_primary_phase" not in json.loads(old)

    failed = cutover.CutoverReceipt(
        ATTEMPT,
        "NO_GO",
        "INDETERMINATE",
        False,
        False,
        None,
        None,
        failed_phase="PREPARE_WORKER",
        worker_primary_phase=primary,
        worker_compensation="INDETERMINATE",
    )
    record = terminal.TerminalRecord.from_receipt(_plan(), failed)
    raw = record.serialized()
    payload = json.loads(raw)
    assert payload["version"] == terminal.VERSION_V2
    assert payload["worker_primary_phase"] == primary
    assert payload["worker_compensation"] == "INDETERMINATE"
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
        terminal.write_once(record, plan=_plan(), lease=lease)
    assert terminal.reconcile_persisted(_plan()) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    terminal.verify_persisted_exact(_plan(), failed)
    with pytest.raises(terminal.TerminalReceiptError, match="differs from original bytes"):
        terminal.verify_persisted_exact(_plan(), replace(failed, worker_primary_phase="START"))


@pytest.mark.parametrize(
    ("exit_code", "oom"),
    [(0, False), (1, False), (137, True), ("UNKNOWN", False), (137, "UNKNOWN")],
)
def test_worker_exit_durable_v3_roundtrip_strict_without_changing_v1_v2(
    exit_code: object, oom: object
) -> None:
    failed = cutover.CutoverReceipt(
        ATTEMPT,
        "NO_GO",
        "INDETERMINATE",
        False,
        False,
        None,
        None,
        failed_phase="PREPARE_WORKER",
        worker_primary_phase="HEALTH_EXITED",
        worker_compensation="VERIFIED",
        worker_exit_code=exit_code,
        worker_oom_killed=oom,
    )
    record = terminal.TerminalRecord.from_receipt(_plan(), failed)
    payload = json.loads(record.serialized())
    assert payload["version"] == terminal.VERSION_V3
    assert payload["worker_exit_code"] == exit_code
    assert payload["worker_oom_killed"] == oom
    assert payload["state"] == "NO_GO"
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
        terminal.write_once(record, plan=_plan(), lease=lease)
    assert terminal.reconcile_persisted(_plan()) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    terminal.verify_persisted_exact(_plan(), failed)


@pytest.mark.parametrize(
    ("exit_code", "oom", "phase"),
    [
        (True, False, "HEALTH_EXITED"),
        (256, True, "HEALTH_EXITED"),
        (-1, False, "HEALTH_EXITED"),
        ("137", True, "HEALTH_EXITED"),
        (137, 1, "HEALTH_EXITED"),
        (137, "true", "HEALTH_EXITED"),
        (137, True, "HEALTH_UNHEALTHY"),
    ],
)
def test_worker_exit_durable_v3_rejects_ambiguous_types_and_wrong_phase(
    exit_code: object, oom: object, phase: str
) -> None:
    record = terminal.TerminalRecord.from_receipt(
        _plan(),
        cutover.CutoverReceipt(
            ATTEMPT,
            "NO_GO",
            "NO_GO",
            False,
            False,
            None,
            None,
            failed_phase="PREPARE_WORKER",
            worker_primary_phase=phase,
            worker_compensation="VERIFIED",
            worker_exit_code=exit_code,
            worker_oom_killed=oom,
        ),
    )
    with pytest.raises(terminal.TerminalReceiptError):
        record.serialized()


def test_worker_exit_durable_v4_preserves_exact_v3_bytes() -> None:
    failed = cutover.CutoverReceipt(
        ATTEMPT,
        "NO_GO",
        "INDETERMINATE",
        False,
        False,
        None,
        None,
        failed_phase="PREPARE_WORKER",
        worker_primary_phase="HEALTH_EXITED",
        worker_compensation="VERIFIED",
        worker_exit_code=1,
        worker_oom_killed=False,
        worker_exit_signature="EMPTY.EXITED.EARLY_LT_5S.NOT_RUN",
    )
    record = terminal.TerminalRecord.from_receipt(_plan(), failed)
    payload = json.loads(record.serialized())
    assert payload["version"] == terminal.VERSION_V4
    assert payload["worker_exit_signature"] == "EMPTY.EXITED.EARLY_LT_5S.NOT_RUN"
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
        terminal.write_once(record, plan=_plan(), lease=lease)
    assert terminal.reconcile_persisted(_plan()) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    terminal.verify_persisted_exact(_plan(), failed)
    with pytest.raises(terminal.TerminalReceiptError):
        terminal.verify_persisted_exact(
            _plan(), replace(failed, worker_exit_signature="UNKNOWN.EXITED.UNKNOWN.UNKNOWN")
        )


@pytest.mark.parametrize(
    "signature", ["OTHER.EXITED.EARLY_LT_5S.NOT_RUN", "PRIVATE", "", "UNKNOWN", 123]
)
def test_worker_exit_durable_v4_rejects_untrusted_signature(signature: object) -> None:
    failed = cutover.CutoverReceipt(
        ATTEMPT,
        "NO_GO",
        "NO_GO",
        False,
        False,
        None,
        None,
        failed_phase="PREPARE_WORKER",
        worker_primary_phase="HEALTH_EXITED",
        worker_compensation="VERIFIED",
        worker_exit_code=1,
        worker_oom_killed=False,
        worker_exit_signature=signature,
    )
    with pytest.raises(terminal.TerminalReceiptError):
        terminal.TerminalRecord.from_receipt(_plan(), failed).serialized()


def test_cutover_terminal_sink_runs_before_release_of_same_lease(tmp_path: Path) -> None:
    class Fake:
        def attest_original(self, _p: object, _l: object) -> None: ...

        def stage(self, _p: object, _l: object) -> None: ...

        def prepare_worker(self, _p: object, _l: object) -> str:
            return WORKER

        def park_original(self, _p: object, _l: object) -> None: ...

        def bootstrap_owner_session(self, _p: object, _l: object) -> None: ...

        def activate_candidate(self, _p: object, _w: object, _l: object) -> str:
            return NEW

        def accept_candidate(self, _p: object, _c: object, _w: object, _l: object) -> None: ...

        def retire_original(self, _p: object, _c: object, _w: object, _l: object) -> None: ...

        def recover_original(self, _p: object, _l: object) -> bool:
            raise AssertionError("no recovery on positive host")

        def finalize(self, _p: object, **_kw: object) -> str:
            return "ACCEPT"

    seen: list[int] = []

    def sink(
        plan: cutover.CutoverPlan, receipt: cutover.CutoverReceipt, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        seen.append(lease.fd)
        terminal.write_once(
            terminal.TerminalRecord.from_receipt(plan, receipt), plan=plan, lease=lease
        )

    result = cutover.run_cutover_a(
        _plan(),
        backend=Fake(),
        terminal_sink=sink,
        terminal_preflight=terminal.prepare_destination,
    )
    assert result.accepted and len(seen) == 1
    assert (tmp_path / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-result-{ATTEMPT}.json").exists()


def test_invalid_or_recovered_terminal_record_never_becomes_acceptance() -> None:
    accepted = terminal.TerminalRecord.from_receipt(_plan(), _accepted())
    for replacement in (
        {"state": "ACCEPTED", "cleanup": "NO_GO"},
        {"candidate_id": None},
        {"worker_id": OLD},
        {"irreversible_commit_started": False},
    ):
        with pytest.raises(terminal.TerminalReceiptError):
            replace(accepted, **replacement).serialized()
    recovery = cutover.CutoverReceipt(ATTEMPT, "RECOVERED", "ACCEPT", True, False, None, WORKER)
    record = terminal.TerminalRecord.from_receipt(_plan(), recovery)
    assert record.state == "RECOVERED" and record.serialized()
    no_go = cutover.CutoverReceipt(ATTEMPT, "NO_GO", "NO_GO", False, True, NEW, WORKER)
    assert terminal.TerminalRecord.from_receipt(_plan(), no_go).serialized()


def test_wrong_lease_or_symlink_never_overwrites_terminal_result(tmp_path: Path) -> None:
    target = tmp_path / "unrelated-user-data.txt"
    target.write_text("preserve")
    plan = _plan()
    record = terminal.TerminalRecord.from_receipt(plan, _accepted())
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        destination = tmp_path / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-result-{ATTEMPT}.json"
        destination.symlink_to(target)
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.write_once(record, plan=plan, lease=lease)
    assert target.read_text() == "preserve"
    with pytest.raises(cleanup.CleanupError):
        terminal.write_once(
            record, plan=plan, lease=cleanup.BocaJobLease(ATTEMPT, -1, os.getpid(), True)
        )


def test_lost_or_failed_sink_cannot_produce_success_receipt(tmp_path: Path) -> None:
    class Fake:
        def __getattr__(self, name: str):
            if name == "prepare_worker":
                return lambda *_args: WORKER
            if name == "activate_candidate":
                return lambda *_args: NEW
            if name == "finalize":
                return lambda *_args, **_kwargs: "ACCEPT"
            return lambda *_args: None

    def failing_sink(_p: object, _r: object, _lease: object) -> None:
        raise terminal.TerminalReceiptError("fake disk full")

    with pytest.raises(terminal.TerminalReceiptError, match="disk full"):
        cutover.run_cutover_a(
            _plan(),
            backend=Fake(),
            terminal_sink=failing_sink,
            terminal_preflight=terminal.prepare_destination,
        )
    assert not (
        tmp_path / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-result-{ATTEMPT}.json"
    ).exists()
    assert terminal.reconcile_persisted(_plan()) == "INTENT_ONLY_NO_GO"


def _reconcile_in_new_process(home: Path, plan: cutover.CutoverPlan) -> str:
    source = (
        "import json,os,sys; from pathlib import Path; "
        "from boca_socios import host_boca_cleanup as c, host_boca_cutover_receipt as r; "
        "from boca_socios.host_boca_cutover import CutoverPlan; "
        "c.EXPECTED_UID=os.geteuid(); "
        "r._account_home=lambda:Path(sys.argv[1]); "
        "r._persistent_mount=lambda _:None; "
        "print(r.reconcile_persisted(CutoverPlan(**json.loads(sys.argv[2]))))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-only inline source
        [sys.executable, "-c", source, str(home), json.dumps(asdict(plan))],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
        # CI runners can pause a subprocess for several seconds during parallel
        # integration suites; the assertion checks durable reconciliation, not
        # startup latency. Keep a bounded deadline without a scheduling flake.
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_new_process_reboot_like_reconciliation_never_promotes_intent_into_go(
    tmp_path: Path,
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
    assert _reconcile_in_new_process(tmp_path, plan) == "INTENT_ONLY_NO_GO"
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.write_once(
            terminal.TerminalRecord.from_receipt(plan, _accepted()), plan=plan, lease=lease
        )
    assert _reconcile_in_new_process(tmp_path, plan) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"


def test_preflight_does_not_touch_backend_when_storage_unavailable(tmp_path: Path) -> None:
    class NeverHost:
        def __getattr__(self, _name: str):
            return lambda *_args, **_kwargs: pytest.fail("preflight must precede host")

    root = tmp_path / terminal.RECEIPT_DIR_NAME
    root.mkdir(mode=0o700)
    root.chmod(0o750)
    with pytest.raises(terminal.TerminalReceiptError, match="directory unsafe"):
        cutover.run_cutover_a(
            _plan(),
            backend=NeverHost(),
            terminal_sink=lambda *_args: None,
            terminal_preflight=terminal.prepare_destination,
        )
    root.chmod(0o700)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
        with pytest.raises(terminal.TerminalReceiptError, match="exclusively"):
            terminal.prepare_destination(_plan(), lease)


def test_tmpfs_home_is_rejected_even_if_uid_and_mode_are_correct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fs = tmp_path / "mountinfo"
    fs.write_text(
        "20 15 8:1 / / rw,relatime - ext4 /dev/vda1 rw\n"
        + f"21 20 0:44 / {tmp_path} rw,nosuid - tmpfs tmpfs rw\n"
    )
    monkeypatch.setattr(terminal, "MOUNTINFO", fs)
    monkeypatch.setattr(terminal, "_persistent_mount", REAL_MOUNT_CHECK)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError, match="not proven persistent"):
            terminal.prepare_destination(_plan(), lease)
    assert not (tmp_path / terminal.RECEIPT_DIR_NAME).exists()


def test_tmpfs_bind_over_receipt_child_is_rejected_even_when_home_is_durable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child = tmp_path / terminal.RECEIPT_DIR_NAME
    child.mkdir(mode=0o700)
    fs = tmp_path / "mountinfo"
    fs.write_text(
        "20 15 8:1 / / rw,relatime - ext4 /dev/vda1 rw\n"
        + f"21 20 0:44 / {child} rw,nosuid - tmpfs tmpfs rw\n"
    )
    monkeypatch.setattr(terminal, "MOUNTINFO", fs)
    monkeypatch.setattr(terminal, "_persistent_mount", REAL_MOUNT_CHECK)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError, match="not proven persistent"):
            terminal.prepare_destination(_plan(), lease)
    assert not list(child.iterdir())


def test_ambiguous_stacked_mount_at_same_path_is_never_assumed_disk_backed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child = tmp_path / terminal.RECEIPT_DIR_NAME
    child.mkdir(mode=0o700)
    fs = tmp_path / "mountinfo"
    fs.write_text(
        "20 15 8:1 / / rw - ext4 /dev/vda1 rw\n"
        + f"21 20 8:1 / {child} rw - ext4 /dev/vda1 rw\n"
        + f"22 21 0:44 / {child} rw - tmpfs tmpfs rw\n"
    )
    monkeypatch.setattr(terminal, "MOUNTINFO", fs)
    monkeypatch.setattr(terminal, "_persistent_mount", REAL_MOUNT_CHECK)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError, match="mount stack ambiguous"):
            terminal.prepare_destination(_plan(), lease)


def test_normal_nested_disk_backed_bind_at_distinct_mountpoint_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child = tmp_path / terminal.RECEIPT_DIR_NAME
    child.mkdir(mode=0o700)
    fs = tmp_path / "mountinfo"
    fs.write_text(
        "20 15 8:1 / / rw - ext4 /dev/vda1 rw\n"
        + f"21 20 8:1 / {tmp_path} rw - ext4 /dev/vda1 rw\n"
        + f"22 21 8:1 / {child} rw - ext4 /dev/vda1 rw\n"
    )
    monkeypatch.setattr(terminal, "MOUNTINFO", fs)
    monkeypatch.setattr(terminal, "_persistent_mount", REAL_MOUNT_CHECK)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
    assert (child / f"boca-cutover-a-intent-{ATTEMPT}.json").is_file()


def test_home_symlink_or_receipt_hardlink_and_foreign_marker_are_no_go(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alias = tmp_path.parent / (tmp_path.name + "-redirect")
    alias.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(terminal, "_account_home", lambda: alias)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError, match="symlink"):
            terminal.prepare_destination(_plan(), lease)
    monkeypatch.setattr(terminal, "_account_home", lambda: tmp_path)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(_plan(), lease)
    directory = tmp_path / terminal.RECEIPT_DIR_NAME
    intent = directory / f"boca-cutover-a-intent-{ATTEMPT}.json"
    hardlink = directory / "boca-cutover-a-intent-41949228861.json"
    os.link(intent, hardlink)
    with pytest.raises(terminal.TerminalReceiptError, match="unsafe file"):
        terminal.reconcile_persisted(_plan())
    hardlink.unlink()
    bad_file = directory / "foreign-unreviewed.txt"
    bad_file.write_text("do-not-remove")
    with pytest.raises(terminal.TerminalReceiptError, match="unknown entries"):
        terminal.reconcile_persisted(_plan())
    assert bad_file.read_text() == "do-not-remove"


def test_terminal_sink_without_early_persistent_preflight_never_enters_backend() -> None:
    class NeverHost:
        def __getattr__(self, _name: str):
            return lambda *_args, **_kwargs: pytest.fail("missing preflight cannot mutate")

    with pytest.raises(cutover.CutoverError, match="prepared before effects"):
        cutover.run_cutover_a(_plan(), backend=NeverHost(), terminal_sink=lambda *_args: None)


def test_concrete_rootless_backend_cannot_dispatch_without_persistent_evidence() -> None:
    source = ReviewedCutoverSources(b"no host", b"no host", b"no host", b"no host")
    real_backend = RootlessCutoverBackend(source)
    with pytest.raises(cutover.CutoverError, match="durable terminal intent and result"):
        cutover.run_cutover_a(_plan(), backend=real_backend)
    with pytest.raises(cutover.CutoverError, match="durable terminal intent and result"):
        cutover.run_cutover_a(_plan(), backend=real_backend, terminal_sink=lambda *_args: None)


@pytest.mark.parametrize(
    "home",
    ["/tmp/boca-deploy", "/run/user/10001", "/srv/boca-socios"],  # noqa: S108
)
def test_production_home_must_not_overlap_ephemeral_or_exact_compose_stage(
    monkeypatch: pytest.MonkeyPatch, home: str
) -> None:
    monkeypatch.setattr(terminal, "_account_home", REAL_ACCOUNT_HOME)
    monkeypatch.setattr(
        terminal.pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_name="boca-deploy", pw_dir=home),
    )
    with pytest.raises(terminal.TerminalReceiptError, match="home untrusted"):
        terminal._account_home()
