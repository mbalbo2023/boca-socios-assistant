"""Pure harness guards for the hosted Linux worker IPC proof.

The development executor denies AF_UNIX creation (EPERM); only a disposable
GitHub-hosted Linux runner can complete the actual cross-UID socket smoke.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "boca_worker_ipc_linux_harness", ROOT / "scripts/check_worker_ipc_linux.py"
)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_hosted_runner_uses_root_owned_ubuntu_python_without_toolcache_loader_env() -> None:
    """Dropped UIDs must not depend on setup-python's stripped LD_LIBRARY_PATH."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        'sudo --non-interactive env PYTHONPATH="$GITHUB_WORKSPACE/src" '
        '/usr/bin/python3 "$GITHUB_WORKSPACE/scripts/check_worker_ipc_linux.py"'
    ) in workflow


def test_runner_failure_reports_only_fixed_stage_without_leaking_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> None:
        raise smoke.SmokeFailure("WORKER_SPAWN")

    monkeypatch.setattr(smoke, "_run_harness", unavailable)
    assert smoke.main([]) == 1
    emitted = capsys.readouterr()
    assert emitted.out == ""
    assert emitted.err == "BOCA_WORKER_IPC_LINUX state=NO_GO stage=WORKER_SPAWN\n"


def test_runner_unexpected_exception_is_generic_and_never_logged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> None:
        raise RuntimeError("SENSITIVE_URL=https://not-for-logs.invalid/token")

    monkeypatch.setattr(smoke, "_run_harness", unavailable)
    assert smoke.main([]) == 1
    emitted = capsys.readouterr()
    assert emitted.out == ""
    assert emitted.err == "BOCA_WORKER_IPC_LINUX state=NO_GO stage=UNKNOWN\n"


@pytest.mark.parametrize(
    ("role", "receipt"),
    [
        ("worker", b"BOCA_WORKER_IPC_WORKER state=STOPPED\n"),
        ("controller", b"BOCA_WORKER_IPC_CONTROLLER state=NO_GO\n"),
        ("stranger", b"BOCA_WORKER_IPC_STRANGER state=DENIED\n"),
    ],
)
def test_accept_only_fixed_nonsecret_child_receipts(role: str, receipt: bytes) -> None:
    smoke.require_fixed_receipt(role, receipt, b"")
    for unsafe in (receipt.rstrip(b"\n"), receipt + b"URL=https://boca.invalid/\n", b"", receipt):
        with pytest.raises(smoke.SmokeFailure):
            smoke.require_fixed_receipt(
                role, unsafe, b"private stderr" if unsafe == receipt else b""
            )


def test_socket_attestation_rejects_missing_as_not_ready_and_unsafe_inode(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.sock"
    assert smoke.socket_ready(path, owner_uid=os.geteuid()) is False
    path.write_bytes(b"not a socket")
    with pytest.raises(smoke.SmokeFailure):
        smoke.socket_ready(path, owner_uid=os.geteuid())
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(smoke.SmokeFailure):
        smoke.socket_ready(path, owner_uid=os.geteuid())


def test_invalid_entrypoint_arguments_never_start_socket_or_children(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert smoke.main(["--worker"]) == 2
    assert smoke.main(["--client", "https://boca.invalid/"]) == 2
    assert smoke.main(["--stranger", str(tmp_path / "synthetic.sock"), "EXTRA"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "BOCA_WORKER_IPC_LINUX state=NO_GO\n" * 3


def test_teardown_terminates_only_the_owned_child_process() -> None:
    process = subprocess.Popen(  # noqa: S603 - fixed synthetic local sleep process
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        smoke.stop_owned_child(process, timeout=0.5)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2)
