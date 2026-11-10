"""Off-host evidence custody before removing an exact worker from Cutover."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios import worker_start_receipt as worker
from test_host_boca_cutover_receipt import ATTEMPT, OLD, WORKER, _accepted, _plan

OBSERVATION = "MODULE_NOT_FOUND_ERROR"
SIGNATURE = "EMPTY.EXITED.EARLY_LT_5S.NOT_RUN"


@pytest.fixture(autouse=True)
def rootless_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(terminal, "_account_home", lambda: tmp_path)
    monkeypatch.setattr(terminal, "_persistent_mount", lambda _path: None)


def marker(tmp_path: Path) -> Path:
    return tmp_path / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-worker-start-{ATTEMPT}.json"


def failed_terminal() -> terminal.TerminalRecord:
    return replace(
        terminal.TerminalRecord.from_receipt(_plan(), _accepted()),
        state="RECOVERED",
        irreversible_commit_started=False,
        original_restored=True,
        candidate_id=None,
        worker_id=None,
        worker_primary_phase="HEALTH_EXITED",
        worker_compensation="VERIFIED",
        worker_exit_code=1,
        worker_oom_killed=False,
        worker_exit_signature=SIGNATURE,
        worker_stderr_observation=OBSERVATION,
    )


def test_capture_is_fsynced_and_recoverable_without_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        intent_sha = terminal.prepare_destination(plan, lease)
        fsync = os.fsync
        synced: list[tuple[int, int]] = []

        def record_fsync(fd: int) -> None:
            info = os.fstat(fd)
            synced.append((info.st_dev, info.st_ino))
            fsync(fd)

        monkeypatch.setattr(os, "fsync", record_fsync)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
        saved = marker(tmp_path)
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600
        assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700
        assert synced == [
            (entry.stat().st_dev, entry.stat().st_ino) for entry in (saved, saved.parent)
        ]
        raw = saved.read_bytes()
        assert json.loads(raw) == {
            "version": "boca-cutover-a-worker-start-v1",
            "attempt_id": ATTEMPT,
            "browser_image_ref": plan.browser_image,
            "target_source_sha": plan.target_sha,
            "intent_sha256": intent_sha,
            "worker_id": WORKER,
            "worker_stderr_observation": OBSERVATION,
        }
        assert len(raw) <= 1024
        with pytest.raises(terminal.TerminalReceiptError, match="exclusively"):
            worker.persist_before_cleanup(plan, lease, WORKER, "EMPTY")
        assert saved.read_bytes() == raw
    assert worker.read_before_cleanup(plan) == (WORKER, OBSERVATION)
    assert terminal.reconcile_persisted(plan) == "INTENT_ONLY_NO_GO"


@pytest.mark.parametrize(
    ("cid", "observation"),
    [
        (OLD, "EMPTY"),
        ("prefix-only", "EMPTY"),
        (WORKER, "AUTHORIZATION: PRIVATE_CANARY"),
        (WORKER, False),
        (WORKER, None),
    ],
)
def test_unknown_input_cannot_enter_private_marker(
    tmp_path: Path, cid: str, observation: Any
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        with pytest.raises(terminal.TerminalReceiptError) as error:
            worker.persist_before_cleanup(plan, lease, cid, observation)
        assert "PRIVATE_CANARY" not in str(error.value)
        assert not marker(tmp_path).exists()


def test_wrong_intent_lease_and_already_terminal_fail_closed(tmp_path: Path) -> None:
    plan = _plan()
    other_image = replace(plan, browser_image=plan.browser_image[:-1] + "0")
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError):
            worker.persist_before_cleanup(plan, lease, WORKER, "EMPTY")
        terminal.prepare_destination(plan, lease)
        with pytest.raises(terminal.TerminalReceiptError):
            worker.persist_before_cleanup(other_image, lease, WORKER, "EMPTY")
    with cleanup.protected_boca_job_lease("17") as other_lease:
        with pytest.raises(cleanup.CleanupError):
            worker.persist_before_cleanup(plan, other_lease, WORKER, "EMPTY")
    with cleanup.protected_boca_job_lease(ATTEMPT) as same_run:
        record = terminal.TerminalRecord.from_receipt(plan, _accepted())
        terminal.write_once(record, plan=plan, lease=same_run)
        with pytest.raises(terminal.TerminalReceiptError):
            worker.persist_before_cleanup(plan, same_run, WORKER, "EMPTY")
        assert not marker(tmp_path).exists()


def test_preflight_keeps_room_for_both_capture_and_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        monkeypatch.setattr(terminal, "MAX_DIRECTORY_ENTRIES", 2)
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.prepare_destination(plan, lease)
        folder = marker(tmp_path).parent
        assert list(folder.iterdir()) == []
        monkeypatch.setattr(terminal, "MAX_DIRECTORY_ENTRIES", 3)
        terminal.prepare_destination(plan, lease)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
        terminal.write_once(failed_terminal(), plan=plan, lease=lease)
        assert terminal.reconcile_persisted(plan) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"


def test_orphaned_evidence_forbids_reusing_the_attempt(tmp_path: Path) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
        saved = marker(tmp_path)
        raw = saved.read_bytes()
        intent = saved.parent / f"boca-cutover-a-intent-{ATTEMPT}.json"
        intent.unlink()
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.prepare_destination(plan, lease)
        assert saved.read_bytes() == raw
        assert not intent.exists()
        with pytest.raises(terminal.TerminalReceiptError):
            worker.read_before_cleanup(plan)


def test_private_reader_rejects_wrong_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
    monkeypatch.setattr(os, "getegid", lambda: cleanup.EXPECTED_UID + 1)
    with pytest.raises(terminal.TerminalReceiptError):
        worker.read_before_cleanup(plan)
    assert marker(tmp_path).is_file()


def test_precleanup_fsync_interruption_keeps_original_and_forbids_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        with monkeypatch.context() as patch:

            def fail_fsync(fd: int) -> None:
                raise OSError("injected")

            patch.setattr(os, "fsync", fail_fsync)
            with pytest.raises(terminal.TerminalReceiptError):
                worker.persist_before_cleanup(plan, lease, WORKER, "EMPTY")
        assert marker(tmp_path).is_file()
        original = marker(tmp_path).read_bytes()
        with pytest.raises(terminal.TerminalReceiptError):
            worker.persist_before_cleanup(plan, lease, WORKER, "TRANSPORT")
        assert marker(tmp_path).read_bytes() == original
        assert terminal.reconcile_persisted(plan) == "INTENT_ONLY_NO_GO"


def test_terminal_v5_requires_matching_precleanup_and_preserves_primary(
    tmp_path: Path,
) -> None:
    plan = _plan()
    record = replace(
        failed_terminal(),
        state="NO_GO",
        cleanup="INDETERMINATE",
        original_restored=False,
        worker_compensation="INDETERMINATE",
    )
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.write_once(record, plan=plan, lease=lease)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.write_once(
                replace(record, worker_stderr_observation="EMPTY"), plan=plan, lease=lease
            )
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.write_once(replace(record, worker_id="0" * 64), plan=plan, lease=lease)
        digest = terminal.write_once(record, plan=plan, lease=lease)
    assert hashlib.sha256(record.serialized()).hexdigest() == digest
    payload = json.loads(record.serialized())
    assert (payload["version"], payload["worker_exit_code"], payload["worker_oom_killed"]) == (
        "boca-cutover-a-terminal-v5",
        1,
        False,
    )
    assert payload["worker_primary_phase"] == "HEALTH_EXITED"
    assert payload["worker_compensation"] == "INDETERMINATE"
    assert terminal.reconcile_persisted(plan) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    marker(tmp_path).unlink()
    with pytest.raises(terminal.TerminalReceiptError):
        terminal.reconcile_persisted(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("worker_exit_signature", None),
        ("worker_exit_code", None),
        ("worker_primary_phase", "START"),
        ("worker_stderr_observation", "PRIVATE_CANARY"),
        ("worker_stderr_observation", False),
    ],
)
def test_terminal_v5_refuses_incomplete_or_arbitrary_evidence(field: str, value: Any) -> None:
    with pytest.raises(terminal.TerminalReceiptError) as error:
        replace(failed_terminal(), **{field: value}).serialized()
    assert "PRIVATE_CANARY" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "image",
        "source",
        "cid",
        "attempt",
        "intent",
        "duplicate",
        "extra",
        "oversize",
        "symlink",
        "fifo",
        "hardlink",
        "mode",
    ],
)
def test_private_reader_rejects_invalid_binding_or_inode(tmp_path: Path, change: str) -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        terminal.prepare_destination(plan, lease)
        worker.persist_before_cleanup(plan, lease, WORKER, OBSERVATION)
    dest = marker(tmp_path)
    data = json.loads(dest.read_bytes())
    bad_values = {
        "image": ("browser_image_ref", "unverified"),
        "source": ("target_source_sha", "b" * 40),
        "cid": ("worker_id", OLD),
        "attempt": ("attempt_id", "18"),
        "intent": ("intent_sha256", "0" * 64),
        "extra": ("secret", "PRIVATE_CANARY"),
    }
    if change in bad_values:
        key, value = bad_values[change]
        data[key] = value
        dest.write_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii"))
    elif change == "duplicate":
        dest.write_bytes(dest.read_bytes()[:-1] + b',"worker_stderr_observation":"EMPTY"}')
    elif change == "oversize":
        dest.write_bytes(b"X" * 2049)
    elif change == "hardlink":
        os.link(dest, tmp_path / "other")
    elif change == "mode":
        dest.chmod(0o644)
    else:
        dest.unlink()
        if change == "fifo":
            os.mkfifo(dest, 0o600)
        else:
            dest.symlink_to(tmp_path / "outside")
    with pytest.raises(terminal.TerminalReceiptError) as error:
        worker.read_before_cleanup(plan)
    assert "PRIVATE_CANARY" not in str(error.value)
