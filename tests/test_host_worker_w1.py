"""One physical Boca-only start in a real in-memory rootless inventory, never a host daemon."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import test_host_lifecycle_rootless_adapter as fixture
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios import host_worker_w1 as w1
from boca_socios import worker_start_capture as capture
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation, WorkerStartFailure
from test_on_demand_end_to_end import WorkerFixture
from test_worker_start_capture import CID, SOCKET, UPGRADE, engine, frame


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"ModuleNotFoundError: No module named 'cryptography'\n", "cryptography"),
        (b"ModuleNotFoundError: No module named 'foo_bar42'\n", "foo_bar42"),
        (b"ModuleNotFoundError: No module named 'private.canary'\n", None),
        (b"ModuleNotFoundError: No module named '../secrets'\n", None),
        (b"ModuleNotFoundError: No module named 'ABC'\n", None),
        (b"ModuleNotFoundError: No module named '" + b"a" * 300 + b"'\n", None),
        (b"ValueError: other failure\n", None),
    ],
)
def test_w1_captures_only_bounded_final_module_from_real_engine_frames(
    monkeypatch: pytest.MonkeyPatch, stderr: bytes, expected: str | None
) -> None:
    _, peer = engine(monkeypatch)
    with peer, w1._w1_tail_capture() as slot:
        peer.sendall(UPGRADE)
        with capture.attach_output(SOCKET, CID) as attached:
            half = len(stderr) // 2
            peer.sendall(frame(2, stderr[:half]) + frame(2, stderr[half:]))
            peer.shutdown(1)  # SHUT_WR
            attached.finish()
        assert slot == [expected]
    assert capture._StderrTail.__name__ == "_StderrTail"


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(adapter, "panel_control_mount", lambda: str(tmp_path / "control"))
    monkeypatch.setattr(w1, "INSTALLED_RUN_ID", fixture.INSTALLED)
    monkeypatch.setattr(w1, "INSTALLED_SOURCE_SHA", fixture.SOURCE)
    monkeypatch.setattr(w1, "_claim_directory", lambda: tmp_path)
    physical = WorkerFixture(tmp_path)
    physical.fields["container", fixture.WORKER, "State.Pid"] = 0
    physical.fields["container", fixture.WORKER, "State.StartedAt"] = "0001-01-01T00:00:00Z"
    physical.fields["container", fixture.WORKER, "State.FinishedAt"] = "0001-01-01T00:00:00Z"
    instance = OnDemandInstallation(
        fixture.INSTALLED,
        fixture.SOURCE,
        fixture.CONTROLLER,
        fixture.CONTROLLER_REF,
        fixture.WORKER,
        fixture.WORKER_REF,
        tmp_path / "boca.sqlite3",
        fixture._binding(),
    )
    monkeypatch.setattr(w1, "read_installed_binding", lambda lease: instance)
    monkeypatch.setattr(w1, "_RootlessIO", lambda item: physical)
    monkeypatch.setattr(w1, "read_panel_status", lambda item: None)
    return physical, tmp_path


def _new_start(physical: WorkerFixture) -> None:
    physical.fields["container", fixture.WORKER, "State.StartedAt"] = "2026-11-10T14:10:00Z"
    physical.fields["container", fixture.WORKER, "State.Pid"] = 27
    physical.set_state(fixture.WORKER, True)


def test_w1_failure_is_new_exact_worker_start_with_cleanup_and_sanitized_module(installed):
    physical, home = installed

    def fail_after_actual_start():
        _new_start(physical)
        physical.set_state(fixture.WORKER, False)
        physical.fields["container", fixture.WORKER, "State.Pid"] = 0
        physical.state = "exited"
        physical.fields["container", fixture.WORKER, "State.FinishedAt"] = "2026-11-10T14:10:01Z"
        raise WorkerStartFailure("MODULE_NOT_FOUND_ERROR", exit_code=1, oom=False)

    physical.after_start = fail_after_actual_start
    evidence = w1._diagnose(fixture.RUN)
    assert evidence["start_result"] == "FAILED"
    assert evidence["cause"] == "MODULE_NOT_FOUND_ERROR"
    assert evidence["exit_code"] == 1
    assert evidence["oom"] is False
    assert evidence["missing_module"] is None  # no fake stderr stream in this fixture
    assert evidence["fresh_start"] is True
    assert evidence["cleanup"] == "VERIFIED"
    assert evidence["post_state"] == "exited"
    assert evidence["post_pid"] == 0
    assert physical.starts_from == ["created"]
    assert physical.stops == 0  # exited on its own; never stop unrelated objects
    claim = home / w1.CLAIM_NAME
    assert stat.S_IMODE(claim.stat().st_mode) == 0o600
    assert json.loads(claim.read_text()) == {"schema": 1, "run_id": fixture.RUN}
    with pytest.raises(w1.W1Unavailable):
        w1._diagnose(fixture.RUN)  # no second start even with a new process
    assert physical.starts_from == ["created"]


def test_w1_healthy_start_is_stopped_exactly_once(installed):
    physical, _ = installed
    physical.after_start = lambda: _new_start(physical)
    stop_original = physical.stop_worker

    def stop_with_docker_pid_transition(worker_id):
        stop_original(worker_id)
        physical.fields["container", fixture.WORKER, "State.Pid"] = 0
        physical.fields["container", fixture.WORKER, "State.FinishedAt"] = "2026-11-10T14:10:01Z"

    physical.stop_worker = stop_with_docker_pid_transition
    evidence = w1._diagnose(fixture.RUN)
    assert evidence["start_result"] == "HEALTHY"
    assert evidence["cause"] == "NONE"
    assert evidence["missing_module"] is None
    assert physical.starts_from == ["created"]
    assert physical.stops == 1
    assert evidence["post_pid"] == 0
    assert evidence["cleanup"] == "VERIFIED"


def test_w1_rejects_bad_binding_before_mutating_docker(installed, monkeypatch):
    physical, home = installed
    monkeypatch.setattr(w1, "INSTALLED_SOURCE_SHA", "e" * 40)
    with pytest.raises(w1.W1Unavailable):
        w1._diagnose(fixture.RUN)
    assert physical.starts_from == []
    assert not (home / w1.CLAIM_NAME).exists()


def test_w1_refuses_preexisting_panel_operation_before_mutation(installed, monkeypatch):
    physical, home = installed
    monkeypatch.setattr(w1, "read_panel_status", lambda _: object())
    with pytest.raises(w1.W1Unavailable):
        w1._diagnose(fixture.RUN)
    assert physical.starts_from == []
    assert not (home / w1.CLAIM_NAME).exists()


def test_w1_refuses_stale_start_timestamp_even_if_exit_status_matches(installed):
    physical, _ = installed

    def fail_without_fresh_witness():
        physical.set_state(fixture.WORKER, False)
        physical.state = "exited"
        raise WorkerStartFailure("MODULE_NOT_FOUND_ERROR", exit_code=1, oom=False)

    physical.after_start = fail_without_fresh_witness
    with pytest.raises(w1.W1Unavailable):
        w1._diagnose(fixture.RUN)
    assert physical.starts_from == ["created"]


def test_w1_runner_rejects_mutated_or_privately_named_receipts(installed):
    physical, _ = installed

    def fail_after_actual_start():
        _new_start(physical)
        physical.set_state(fixture.WORKER, False)
        physical.fields["container", fixture.WORKER, "State.Pid"] = 0
        physical.state = "exited"
        physical.fields["container", fixture.WORKER, "State.FinishedAt"] = "2026-11-10T14:10:01Z"
        raise WorkerStartFailure("MODULE_NOT_FOUND_ERROR", exit_code=1, oom=False)

    physical.after_start = fail_after_actual_start
    valid = w1._diagnose(fixture.RUN)
    line = w1._checked(valid, fixture.RUN)
    assert line.startswith("BOCA_WORKER_W1 ")
    assert w1._checked(json.loads(line.removeprefix("BOCA_WORKER_W1 ")), fixture.RUN) == line
    for mutation in (
        {"missing_module": "private.canary"},
        {"post_pid": 123},
        {"cleanup": "UNKNOWN"},
        {"start_result": "HEALTHY", "cause": "MODULE_NOT_FOUND_ERROR"},
        {"run_id": "99999999999999999"},
    ):
        with pytest.raises(w1.W1Unavailable):
            w1._checked({**valid, **mutation}, fixture.RUN)
