"""Pure harness guards for the hosted Linux worker IPC proof.

The development executor denies AF_UNIX creation (EPERM); only a disposable
GitHub-hosted Linux runner can complete the actual cross-UID socket smoke.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "boca_worker_ipc_linux_harness", ROOT / "scripts/check_worker_ipc_linux.py"
)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


@pytest.mark.parametrize(
    ("owner", "group", "mode", "accepted"),
    [
        (0, 0, 0o1777, True),
        (0, 0, 0o0777, False),
        (1001, 1001, 0o1777, False),
        (0, 1001, 0o1777, False),
    ],
)
def test_shared_temp_requires_root_owned_sticky_mount(
    monkeypatch: pytest.MonkeyPatch, owner: int, group: int, mode: int, accepted: bool
) -> None:
    original = Path.lstat

    def controlled_stat(self: Path) -> object:
        if str(self) == "/tmp":  # noqa: S108 - simulated trusted root in fixture
            return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=owner, st_gid=group)
        return original(self)

    monkeypatch.setattr(Path, "lstat", controlled_stat)
    if accepted:
        assert smoke._safe_temp_base() == Path("/tmp")  # noqa: S108 - test-only source
    else:
        with pytest.raises(smoke.SmokeFailure, match="untrusted runner temporary mount"):
            smoke._safe_temp_base()


def test_cross_uid_fixture_uses_shared_tmp_not_runner_private_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub may set TMPDIR under an owner-only /home/runner parent."""
    captured: dict[str, object] = {}

    def private_tmpdir(*args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        raise OSError("private sandbox")

    monkeypatch.setattr(smoke.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        smoke,
        "_safe_temp_base",
        lambda: Path("/tmp"),  # noqa: S108 - test-only trusted stub
    )
    monkeypatch.setattr(smoke.tempfile, "TemporaryDirectory", private_tmpdir)
    with pytest.raises(smoke.SmokeFailure, match="^SETUP$"):
        smoke._run_harness()
    assert captured["dir"] == Path("/tmp")  # noqa: S108 - exact fixture policy


def test_child_uses_root_owned_readonly_whitelisted_fixture(tmp_path: Path) -> None:
    """Distant UID can import the reviewed stdlib-only transport from /tmp."""
    fixture_script = smoke._stage_fixture(tmp_path)
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert fixture_script == tmp_path / "scripts/check_worker_ipc_linux.py"
    assert fixture_script.read_bytes() == (ROOT / "scripts/check_worker_ipc_linux.py").read_bytes()
    assert len(smoke._FIXTURE_FILES) == 11
    assert all(
        "synthetic.py" not in path and "ipc_worker.py" not in path for path in smoke._FIXTURE_FILES
    )
    for item in smoke._FIXTURE_FILES:
        destination = tmp_path / item
        assert destination.read_bytes() == (ROOT / item).read_bytes()
        assert stat.S_IMODE(destination.stat().st_mode) == 0o444
    assert stat.S_IMODE((tmp_path / "src").stat().st_mode) == 0o555
    args = smoke._spawn_args("--worker", tmp_path / "ipc/synthetic.sock", fixture_script)
    assert args[1] == str(fixture_script)
    env = smoke._child_env(tmp_path / "src")
    assert env["PYTHONPATH"] == str(tmp_path / "src")
    assert "LD_LIBRARY_PATH" not in env


def test_exited_worker_reports_fixed_bind_substage_without_private_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExitedChild:
        def poll(self) -> int:
            return 1

    monkeypatch.setattr(smoke.os, "geteuid", lambda: 0)
    monkeypatch.setattr(smoke.os, "chown", lambda *_: None)
    monkeypatch.setattr(smoke, "_safe_temp_base", lambda: tmp_path)
    monkeypatch.setattr(
        smoke, "_stage_fixture", lambda root: root / "scripts/check_worker_ipc_linux.py"
    )
    monkeypatch.setattr(smoke.subprocess, "Popen", lambda *_, **__: ExitedChild())
    with pytest.raises(smoke.SmokeFailure, match="^WORKER_BIND_CHILD_EXIT$"):
        smoke._run_harness()


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
