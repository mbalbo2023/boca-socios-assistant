"""Single Boca-only physical worker diagnosis; no engine request, deploy or Cutover."""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from boca_socios import host_first_deploy as deploy
from boca_socios import host_on_demand_service as service
from boca_socios import worker_start_capture as capture
from boca_socios.host_boca_cleanup import protected_boca_job_lease
from boca_socios.host_on_demand_lifecycle import (
    WorkerStartFailure,
    _RootlessIO,
    read_panel_status,
)
from boca_socios.host_on_demand_service import read_installed_binding
from boca_socios.worker_start_capture import is_capture_result

# Historical *installed* source / Cutover #926, NOT the future W1 workflow SHA.
INSTALLED_SOURCE_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"
INSTALLED_RUN_ID = "42806447101"
CLAIM_NAME = ".boca-worker-w1-42806447101.claim"
_PROBE_ID = "00000000-0000-4000-8000-000000000001"
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_CID = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = "BOCA_WORKER_W1 "
_NO_GO = _PREFIX + "result=NO_GO"
_MAX_RECEIPT = 1536
_SAFE_MODULE = re.compile(rb"ModuleNotFoundError: No module named '([a-z_][a-z0-9_.]*)'\Z")
_PRIVATE_ROOTS = frozenset(
    {"private", "secrets", "secret", "credentials", "credential", "password", "token", "keys"}
)
_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "installation_run_id",
        "source_sha",
        "worker_id",
        "fresh_start",
        "start_result",
        "cause",
        "missing_module",
        "exit_code",
        "oom",
        "post_state",
        "post_pid",
        "controller",
        "engine",
        "panel_operation",
        "cleanup",
    }
)


class W1Unavailable(ValueError):
    """The one permitted start could not be proved safe and conclusive."""


def _safe_missing_module(line: bytes, *, newline: bool = False) -> str | None:
    """Permit only a bounded module identifier, never raw process stderr."""
    match = _SAFE_MODULE.fullmatch(line.removesuffix(b"\r") if newline else line)
    if match is None or len(match[1]) > 96:
        return None
    parts = match[1].decode("ascii").split(".")
    if (
        len(parts) > 7
        or any(not part or len(part) > 32 for part in parts)
        or any(part in _PRIVATE_ROOTS for part in parts)
    ):
        return None
    return ".".join(parts)


def _safe_identifier(value: object) -> bool:
    return (
        type(value) is str
        and value.isascii()
        and len(value) <= 96
        and _safe_missing_module(capture._MISSING + b"'" + value.encode("ascii") + b"'") == value
    )


@contextmanager
def _w1_tail_capture() -> Iterator[list[str | None]]:
    """Observe one ephemeral attach without modifying the pinned Cutover source.

    The existing physical Docker attach, frame parsing, budgets and public
    categorical classifier remain unchanged. This W1-only host memfd executes
    in its own Python process and intercepts *only* the final bounded stderr
    line from that parser. It is not installed into the live controller.
    """
    slot: list[str | None] = [None]
    old = capture._StderrTail

    class DiagnosticTail(capture._StderrTail):
        def __init__(self) -> None:
            super().__init__()
            self.last_module: str | None = None

        def feed(self, data: bytes) -> None:
            before, newline, _tail = data.rpartition(b"\n")
            if newline:
                _, previous, line = before.rpartition(b"\n")
                prefix = b"" if previous else self.prefix
                bounded = prefix + line[: capture._PREFIX_BYTES - len(prefix)]
                self.last_module = _safe_missing_module(bounded, newline=True)
            super().feed(data)

        def result(self, saw_stdout: bool) -> capture.CaptureResult:
            category = super().result(saw_stdout)
            if category is capture.CaptureResult.MODULE_NOT_FOUND_ERROR or category.name.startswith(
                "MISSING_"
            ):
                slot[0] = _safe_missing_module(self.prefix) if self.prefix else self.last_module
            return category

    vars(capture)["_StderrTail"] = DiagnosticTail
    try:
        yield slot
    finally:
        vars(capture)["_StderrTail"] = old


@dataclass(frozen=True)
class _Physical:
    state: str
    pid: int
    started_ns: int | None
    finished_ns: int | None


def _claim_directory() -> Path:
    """The existing verified Boca UID10001 home, outside the strict control allowlist."""
    return service._home()


def _claim_once(run_id: str) -> None:
    home = _claim_directory()
    if not home.is_absolute() or home.is_symlink():
        raise W1Unavailable
    directory = home.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.geteuid()
        or directory.st_gid != os.getegid()
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        raise W1Unavailable
    path = home / CLAIM_NAME
    content = json.dumps({"schema": 1, "run_id": run_id}, sort_keys=True).encode("ascii")
    # Claim is committed before Docker START and never deleted. A prior attempt,
    # even one with an uncertain ACK, permanently prevents an accidental retry.
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise W1Unavailable from None
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            if handle.write(content) != len(content):
                raise W1Unavailable
            handle.flush()
            os.fsync(handle.fileno())
        home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(home_fd)
        finally:
            os.close(home_fd)
    except Exception:
        # Retain a possibly incomplete exclusive marker; NEVER allow a second
        # start if the first host process died while claiming ownership.
        raise W1Unavailable from None


def _physical(io: _RootlessIO, installed: Any, coords: Any, lease: Any) -> _Physical:
    snapshot = io.observe(coords, lease)
    if (
        snapshot.require(coords) is not False
        or snapshot.bot_engine_running is not False
        or not snapshot.controller_running
        or not snapshot.controller_healthy
    ):
        # LifecycleHostSnapshot.require returns worker_running, so a True result
        # indicates the worker is running. W1 only observes before / after STOP.
        raise W1Unavailable
    state = io.worker_state(installed.worker_id)
    pid = io.field("container", installed.worker_id, "State.Pid")
    timestamp = io.field("container", installed.worker_id, "State.StartedAt")
    finished = io.field("container", installed.worker_id, "State.FinishedAt")
    if (
        state not in ("created", "exited")
        or type(pid) is not int
        or pid != 0
        or type(timestamp) is not str
        or type(finished) is not str
    ):
        raise W1Unavailable
    started_ns = deploy._worker_rfc3339nano_ns(timestamp)
    finished_ns = deploy._worker_rfc3339nano_ns(finished)
    if state == "exited" and (
        started_ns is None or finished_ns is None or finished_ns < started_ns
    ):
        raise W1Unavailable
    return _Physical(state, pid, started_ns, finished_ns)


def _diagnose(run_id: str) -> dict[str, object]:
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        raise W1Unavailable
    with protected_boca_job_lease(run_id) as lease:
        installed = read_installed_binding(lease)
        if (
            installed.source_sha != INSTALLED_SOURCE_SHA
            or installed.installation_run_id != INSTALLED_RUN_ID
        ):
            raise W1Unavailable
        coords = replace(installed.coordinates(_PROBE_ID), attempt_id=run_id)
        io = _RootlessIO(installed)
        before = _physical(io, installed, coords, lease)
        if before.state != "created" or read_panel_status(installed) is not None:
            raise W1Unavailable

        attempted = False
        failure: WorkerStartFailure | None = None

        def before_start() -> None:
            nonlocal attempted
            _claim_once(run_id)
            attempted = True

        with _w1_tail_capture() as module_slot:
            try:
                try:
                    io.start_worker(installed, "created", before_start)
                except WorkerStartFailure as exc:
                    failure = exc
            finally:
                # Lost ACK may still have started the worker. Stop only this CID.
                if attempted and io.worker_state(installed.worker_id) == "running":
                    io.stop_worker(installed.worker_id)

        if not attempted:
            raise W1Unavailable
        after = _physical(io, installed, coords, lease)
        if (
            after.state != "exited"
            or after.started_ns is None
            or after.started_ns <= (before.started_ns or 0)
            or read_panel_status(installed) is not None
        ):
            raise W1Unavailable

        return {
            "schema": 1,
            "run_id": run_id,
            "installation_run_id": installed.installation_run_id,
            "source_sha": installed.source_sha,
            "worker_id": installed.worker_id,
            "fresh_start": True,
            "start_result": "FAILED" if failure else "HEALTHY",
            "cause": failure.cause if failure else "NONE",
            "missing_module": module_slot[0] if failure else None,
            "exit_code": failure.exit_code if failure else None,
            "oom": failure.oom if failure else None,
            "post_state": after.state,
            "post_pid": after.pid,
            "controller": "HEALTHY",
            "engine": "STOPPED",
            "panel_operation": None,
            "cleanup": "VERIFIED",
        }


def _checked(document: object, run_id: str) -> str:
    if type(document) is not dict or document.keys() != _FIELDS or not _RUN.fullmatch(run_id):
        raise W1Unavailable
    if (
        type(document["schema"]) is not int
        or document["schema"] != 1
        or document["run_id"] != run_id
        or document["installation_run_id"] != INSTALLED_RUN_ID
        or document["source_sha"] != INSTALLED_SOURCE_SHA
        or type(document["worker_id"]) is not str
        or not _CID.fullmatch(document["worker_id"])
        or document["fresh_start"] is not True
        or document["start_result"] not in ("FAILED", "HEALTHY")
        or document["post_state"] != "exited"
        or type(document["post_pid"]) is not int
        or document["post_pid"] != 0
        or document["controller"] != "HEALTHY"
        or document["engine"] != "STOPPED"
        or document["panel_operation"] is not None
        or document["cleanup"] != "VERIFIED"
    ):
        raise W1Unavailable
    cause = document["cause"]
    missing_module = document["missing_module"]
    if (
        type(cause) is not str
        or cause != "NONE"
        and not is_capture_result(cause)
        and cause
        not in {
            "CAPTURE_PREFLIGHT",
            "WORKER_START",
            "HEALTH_WAIT",
            "HEALTH_UNHEALTHY",
            "HEALTH_TIMEOUT",
            "TRANSPORT",
        }
        or missing_module is not None
        and (
            not _safe_identifier(missing_module)
            or not (cause == "MODULE_NOT_FOUND_ERROR" or cause.startswith("MISSING_"))
        )
        or document["start_result"] == "HEALTHY"
        and (
            cause != "NONE"
            or missing_module is not None
            or document["exit_code"] is not None
            or document["oom"] is not None
        )
        or document["start_result"] == "FAILED"
        and cause == "NONE"
        or document["exit_code"] is not None
        and (type(document["exit_code"]) is not int or not 0 <= document["exit_code"] <= 255)
        or document["oom"] is not None
        and type(document["oom"]) is not bool
    ):
        raise W1Unavailable
    line = _PREFIX + json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if len(line.encode("ascii")) > _MAX_RECEIPT:
        raise W1Unavailable
    return line


def _arm_signals() -> None:
    def interrupt(_number: int, _frame: object) -> None:
        # A normal SSH TERM/HUP must unwind the exact-CID STOP finally block.
        raise W1Unavailable

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, interrupt)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 2 or args[0] not in ("host", "verify"):
            raise W1Unavailable
        run_id = args[1]
        if type(run_id) is not str or not _RUN.fullmatch(run_id):
            raise W1Unavailable
        if args[0] == "host":
            _arm_signals()
            document = _diagnose(run_id)
            line = _checked(document, run_id)
        else:
            raw = sys.stdin.buffer.read(_MAX_RECEIPT + 1)
            if not raw.startswith(_PREFIX.encode("ascii")) or len(raw) > _MAX_RECEIPT:
                raise W1Unavailable
            document = json.loads(raw[len(_PREFIX) :].decode("ascii"))
            line = _checked(document, run_id)
            if line.encode("ascii") != raw:
                raise W1Unavailable
    except BaseException:
        # All Docker exceptions, raw stderr and host paths remain private.
        print(_NO_GO)
        return 3
    sys.stdout.write(line)
    return 4 if document["start_result"] == "FAILED" and args[0] == "verify" else 0


if __name__ == "__main__":
    raise SystemExit(main())
