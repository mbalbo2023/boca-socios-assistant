"""No-host O_EXCL terminal attestation and same-lease persistence tests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover as cutover
from boca_socios import host_boca_cutover_receipt as terminal

ATTEMPT = "41949228860"
OLD = "1" * 64
NEW = "2" * 64
WORKER = "3" * 64


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


def test_terminal_result_is_o_excl_fsynced_and_readback_with_same_lease(tmp_path: Path) -> None:
    record = terminal.TerminalRecord.from_receipt(_plan(), _accepted())
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        digest = terminal.write_once(record, lease=lease)
        marker = tmp_path / f"boca-cutover-a-result-{ATTEMPT}.json"
        raw = marker.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        contents = json.loads(raw)
        assert contents["state"] == "ACCEPTED"
        assert contents["cleanup"] == "ACCEPT"
        assert contents["legacy_id"] == OLD
        assert contents["candidate_id"] == NEW
        assert contents["worker_id"] == WORKER
        with pytest.raises(terminal.TerminalReceiptError, match="exclusively"):
            terminal.write_once(record, lease=lease)
        assert marker.read_bytes() == raw


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
        terminal.write_once(terminal.TerminalRecord.from_receipt(plan, receipt), lease=lease)

    result = cutover.run_cutover_a(_plan(), backend=Fake(), terminal_sink=sink)
    assert result.accepted and len(seen) == 1
    assert (tmp_path / f"boca-cutover-a-result-{ATTEMPT}.json").exists()


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
    destination = tmp_path / f"boca-cutover-a-result-{ATTEMPT}.json"
    destination.symlink_to(target)
    record = terminal.TerminalRecord.from_receipt(_plan(), _accepted())
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(terminal.TerminalReceiptError):
            terminal.write_once(record, lease=lease)
    assert target.read_text() == "preserve"
    with pytest.raises(cleanup.CleanupError):
        terminal.write_once(record, lease=cleanup.BocaJobLease(ATTEMPT, -1, os.getpid(), True))


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
        cutover.run_cutover_a(_plan(), backend=Fake(), terminal_sink=failing_sink)
    assert not (tmp_path / f"boca-cutover-a-result-{ATTEMPT}.json").exists()
