"""Linux-runner proof of the *real* Boca browser AF_UNIX transport, offline.

This is a disposable, cross-UID socket test, not a rootless-container or
Chromium acceptance test. It never loads the owner's navigation modules, a
SITE_URL, Docker, SSH, credentials or any IP connection. The worker's cgroup
and network check is substituted ONLY for this host-runner fixture; its real
socket inode, framing, SO_PEERCRED and default NO_GO executor are unchanged.

GitHub's ordinary Linux runner permits AF_UNIX and passwordless sudo; the
managed development executor denies socket(AF_UNIX) with EPERM, so this smoke
must be reported UNVERIFIED until the exact-SHA GitHub step has passed.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import REQUEST, SyntheticIPCError, framed
from boca_socios.browser.ipc_server import UnixSyntheticWorker

WORKER_UID = 10002
CONTROLLER_UID = 10001
STRANGER_UID = 10003
TIMEOUT_SECONDS = 5.0

# This runner-only fixture includes the byte-identical transport and its
# stdlib-only imports. No owner navigation modules, credentials or site data.
# GitHub may use a non-traversable /home/runner/work ancestor after UID drop;
# child processes execute only this root-owned, readonly /tmp copy.
_FIXTURE_FILES = (
    "scripts/check_worker_ipc_linux.py",
    "src/boca_socios/__init__.py",
    "src/boca_socios/browser/__init__.py",
    "src/boca_socios/browser/ipc_client.py",
    "src/boca_socios/browser/ipc_protocol.py",
    "src/boca_socios/browser/ipc_server.py",
    "src/boca_socios/browser/activity_events.py",
    "src/boca_socios/browser/contracts.py",
    "src/boca_socios/browser/worker_health.py",
    "src/boca_socios/domain/__init__.py",
    "src/boca_socios/domain/policy.py",
)

# Public runner-only failure receipts; none contains a URL, path, PID, token,
# user-provided exception or the dropped-UID child's captured stderr.
_STAGES = frozenset(
    {
        "SETUP",
        "WORKER_SPAWN",
        "WORKER_BIND",
        "WORKER_BIND_CHILD_EXIT",
        "WORKER_BIND_INODE",
        "WORKER_BIND_TIMEOUT",
        "STRANGER",
        "CONTROLLER",
        "STOP",
        "CLEANUP",
    }
)

_RECEIPTS = {
    "worker": b"BOCA_WORKER_IPC_WORKER state=STOPPED\n",
    "controller": b"BOCA_WORKER_IPC_CONTROLLER state=NO_GO\n",
    "stranger": b"BOCA_WORKER_IPC_STRANGER state=DENIED\n",
}


class SmokeFailure(RuntimeError):
    """A bounded, nonsecret test contract was not satisfied."""


def require_fixed_receipt(role: str, stdout: bytes, stderr: bytes) -> None:
    """Discard child output unless it is exactly the reviewed public receipt."""
    if role not in _RECEIPTS or stdout != _RECEIPTS[role] or stderr:
        raise SmokeFailure("unexpected offline IPC child receipt")


def socket_ready(path: Path, *, owner_uid: int = WORKER_UID) -> bool:
    """Require the exact inode, UID/GID, mode and link count before connecting."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != owner_uid
        or info.st_gid != owner_uid
        or stat.S_IMODE(info.st_mode) != 0o622
        or info.st_nlink != 1
    ):
        raise SmokeFailure("unverified synthetic socket inode")
    return True


def stop_owned_child(
    process: subprocess.Popen[bytes], *, timeout: float = 0.5
) -> tuple[bytes, bytes]:
    """Stop only our own Popen PID; never send to a group, host daemon or name."""
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=timeout)
        raise SmokeFailure("owned offline worker teardown timeout") from None


async def _serve_worker(path: Path) -> None:
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stopping.set)
    # Only cgroup/network topology is unavailable on the runner; real peer
    # authentication and socket inode checks remain active in UnixSyntheticWorker.
    worker = UnixSyntheticWorker(socket_path=path, boundary_check=lambda: None)
    await worker.serve_until(stopping)


async def _call_worker(path: Path) -> None:
    client = UnixSyntheticBrowser(socket_path=path)
    try:
        try:
            await client.simulate_general_reservation()
        except SyntheticIPCError as exc:
            if str(exc) != "worker_no_go":
                raise SmokeFailure("authorized IPC result was not NO_GO") from None
        else:
            raise SmokeFailure("default offline executor returned success")
    finally:
        await client.close()


def _reject_stranger(path: Path) -> None:
    """A real UID10003 process is rejected by the server's SO_PEERCRED."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(2)
        peer.connect(str(path))
        try:
            peer.sendall(framed(REQUEST))
            peer.shutdown(socket.SHUT_WR)
            data = peer.recv(128)
        except (BrokenPipeError, ConnectionResetError):
            # A rejected peer can race the server's immediate close.
            data = b""
        if data:
            raise SmokeFailure("unauthorized peer received a response frame")


def _child_path(raw: str) -> Path:
    path = Path(raw)
    if (
        not path.is_absolute()
        or path.name != "synthetic.sock"
        or path.parent.name != "ipc"
        or not path.parent.parent.name.startswith("boca-worker-ipc-ci-")
        or len(os.fsencode(path)) >= 104
    ):
        raise SmokeFailure("unreviewed temporary IPC path")
    return path


def _child(mode: str, path: Path) -> int:
    expected_uid = {
        "--worker": WORKER_UID,
        "--controller": CONTROLLER_UID,
        "--stranger": STRANGER_UID,
    }[mode]
    if (os.geteuid(), os.getegid()) != (expected_uid, expected_uid):
        raise SmokeFailure("cross-UID child identity unverified")
    if mode == "--worker":
        asyncio.run(_serve_worker(path))
        sys.stdout.buffer.write(_RECEIPTS["worker"])
    elif mode == "--controller":
        asyncio.run(_call_worker(path))
        sys.stdout.buffer.write(_RECEIPTS["controller"])
    else:
        _reject_stranger(path)
        sys.stdout.buffer.write(_RECEIPTS["stranger"])
    return 0


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise SmokeFailure("offline IPC smoke timed out")
    return seconds


def _safe_temp_base() -> Path:
    """Require GitHub's root-owned sticky shared temp mount for UID drops."""
    base = Path("/tmp")  # noqa: S108 - attest root-owned 01777 before mkdtemp
    info = base.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o1777
    ):
        raise SmokeFailure("untrusted runner temporary mount")
    return base


def _stage_fixture(root: Path) -> Path:
    """Copy only immutable, fixed Boca IPC modules for separate Linux UIDs."""
    if root.is_symlink() or not root.is_dir():
        raise SmokeFailure("unreviewed fixture directory")
    root.chmod(0o755)
    trusted_root = Path(__file__).resolve().parents[1]
    created_dirs: set[Path] = set()
    for relative in _FIXTURE_FILES:
        source = trusted_root / relative
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 200_000:
            raise SmokeFailure("unreviewed fixture source")
        destination = root / relative
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        created_dirs.add(destination.parent)
        data = source.read_bytes()
        destination.write_bytes(data)
        destination.chmod(0o444)
        if destination.read_bytes() != data:
            raise SmokeFailure("fixture copy not verified")
    # UID10001/2/3 can traverse but cannot mutate the code being measured.
    for directory in sorted(created_dirs, key=lambda item: len(item.parts), reverse=True):
        directory.chmod(0o555)
        for parent in directory.parents:
            if parent == root:
                break
            if root in parent.parents:
                parent.chmod(0o555)
    return root / _FIXTURE_FILES[0]


def _spawn_args(mode: str, path: Path, script: Path | None = None) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve() if script is None else script),
        mode,
        str(path),
    ]


def _child_env(source_directory: Path | None = None) -> dict[str, str]:
    """Intentionally do not propagate Actions secrets, proxies or tokens."""
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(
            Path(__file__).resolve().parents[1] / "src"
            if source_directory is None
            else source_directory
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "LC_ALL": "C.UTF-8",
    }


def _run_child(
    mode: str,
    path: Path,
    uid: int,
    deadline: float,
    *,
    script: Path | None = None,
    source_directory: Path | None = None,
) -> None:
    result = subprocess.run(  # noqa: S603 - fixed Python binary and child role
        _spawn_args(mode, path, script),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=_child_env(source_directory),
        user=uid,
        group=uid,
        extra_groups=(),
        timeout=_remaining(deadline),
        check=False,
    )
    if result.returncode != 0:
        raise SmokeFailure("offline IPC child failed")
    require_fixed_receipt(mode.removeprefix("--"), result.stdout, result.stderr)


def _run_harness() -> None:
    if os.name != "posix" or sys.platform != "linux" or os.geteuid() != 0:
        raise SmokeFailure("requires disposable Linux runner root harness")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    stage = "SETUP"
    try:
        with tempfile.TemporaryDirectory(
            prefix="boca-worker-ipc-ci-", dir=_safe_temp_base()
        ) as temporary:
            root = Path(temporary)
            # A reviewed immutable fixture avoids relying on checkout access
            # under a dropped UID while preserving byte-identical Boca IPC.
            script = _stage_fixture(root)
            source_directory = root / "src"
            ipc_directory = root / "ipc"
            ipc_directory.mkdir(mode=0o711)
            os.chown(ipc_directory, WORKER_UID, WORKER_UID)
            ipc_directory.chmod(0o711)
            path = ipc_directory / "synthetic.sock"
            worker: subprocess.Popen[bytes] | None = None
            try:
                stage = "WORKER_SPAWN"
                worker = subprocess.Popen(  # noqa: S603 - fixed Python worker entrypoint
                    _spawn_args("--worker", path, script),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=_child_env(source_directory),
                    user=WORKER_UID,
                    group=WORKER_UID,
                    extra_groups=(),
                )
                stage = "WORKER_BIND"
                while True:
                    try:
                        ready = socket_ready(path)
                    except SmokeFailure:
                        stage = "WORKER_BIND_INODE"
                        raise
                    if ready:
                        break
                    if worker.poll() is not None:
                        stage = "WORKER_BIND_CHILD_EXIT"
                        raise SmokeFailure("offline IPC listener exited before bind")
                    try:
                        time.sleep(min(0.02, _remaining(deadline)))
                    except SmokeFailure:
                        stage = "WORKER_BIND_TIMEOUT"
                        raise
                stage = "STRANGER"
                _run_child(
                    "--stranger",
                    path,
                    STRANGER_UID,
                    deadline,
                    script=script,
                    source_directory=source_directory,
                )
                stage = "CONTROLLER"
                _run_child(
                    "--controller",
                    path,
                    CONTROLLER_UID,
                    deadline,
                    script=script,
                    source_directory=source_directory,
                )
                stage = "STOP"
                if worker.poll() is not None:
                    raise SmokeFailure("offline IPC worker exited before STOP")
                output, error = stop_owned_child(worker, timeout=_remaining(deadline))
                if worker.returncode != 0:
                    raise SmokeFailure("offline IPC STOP exited nonzero")
                require_fixed_receipt("worker", output, error)
                stage = "CLEANUP"
                if path.exists() or path.is_symlink():
                    raise SmokeFailure("offline IPC socket survived STOP")
            finally:
                if worker is not None and worker.poll() is None:
                    stop_owned_child(worker, timeout=0.5)
    except (SmokeFailure, SyntheticIPCError, OSError, RuntimeError, subprocess.TimeoutExpired):
        # Discard every private exception/child stderr; retain only the exact
        # phase that needs independent RCA on a hosted disposable runner.
        raise SmokeFailure(stage) from None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and (len(args) != 2 or args[0] not in {"--worker", "--controller", "--stranger"}):
        print("BOCA_WORKER_IPC_LINUX state=NO_GO", file=sys.stderr)
        return 2
    try:
        if args:
            return _child(args[0], _child_path(args[1]))
        _run_harness()
    except (
        SmokeFailure,
        SyntheticIPCError,
        OSError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        stage = str(exc) if isinstance(exc, SmokeFailure) and str(exc) in _STAGES else "UNKNOWN"
        print(f"BOCA_WORKER_IPC_LINUX state=NO_GO stage={stage}", file=sys.stderr)
        return 1
    print(
        "BOCA_WORKER_IPC_LINUX state=PASS peer=UID10001_10002 stranger=DENIED result=NO_GO stop=VERIFIED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
