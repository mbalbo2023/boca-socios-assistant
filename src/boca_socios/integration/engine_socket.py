"""Private AF_UNIX control of the *real* synthetic command-loop thread.

This listener exists only inside the Boca controller container's private /tmp.
It never binds an IP port, contacts Boca/Telegram, or accesses host Docker.
Future authorized Boca Actions may use an exact-ID rootless `docker exec` to
invoke this module as a client; no GitHub workflow currently does so.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from boca_socios.integration.command_host import BetaCommandHost

ControlOp = Literal["status", "start", "stop"]
ControlState = Literal["RUNNING", "STOPPED", "UNKNOWN"]

DEFAULT_SOCKET = Path("/tmp/boca-socios-engine-v1.sock")  # noqa: S108 - container tmpfs
_FRAME_LIMIT = 192
_REPLY_LIMIT = 256


class LocalEngineUnavailable(RuntimeError):
    """No authentic private controller-engine status or change receipt."""


@dataclass(frozen=True, slots=True)
class EngineReceipt:
    state: ControlState
    changed: bool
    pid: int

    def _as_bytes(self) -> bytes:
        frame = (
            json.dumps(
                {"version": 1, "state": self.state, "changed": self.changed, "pid": self.pid},
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
        if len(frame) > _REPLY_LIMIT:
            raise LocalEngineUnavailable("Boca engine receipt unbounded")
        return frame


def _read_frame(client: socket.socket, limit: int) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        chunk = client.recv(min(128, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
    if not data.endswith(b"\n") or data.count(b"\n") != 1 or len(data) > limit:
        raise LocalEngineUnavailable("Boca engine control frame invalid")
    return bytes(data[:-1])


def _unique_object(raw: bytes) -> dict[str, object]:
    def without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate Boca engine receipt key")
            output[key] = value
        return output

    try:
        document = json.loads(raw.decode("ascii"), object_pairs_hook=without_duplicates)
    except (UnicodeError, ValueError, TypeError):
        raise LocalEngineUnavailable("Boca engine control JSON invalid") from None
    if not isinstance(document, dict):
        raise LocalEngineUnavailable("Boca engine control object invalid")
    return document


def _check_path(path: Path) -> tuple[int, int]:
    try:
        info = path.lstat()
    except OSError:
        raise LocalEngineUnavailable("Boca engine socket unavailable") from None
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or not path.is_absolute()
    ):
        raise LocalEngineUnavailable("Boca engine socket identity invalid")
    return info.st_dev, info.st_ino


def request_local_engine(operation: ControlOp, *, path: Path = DEFAULT_SOCKET) -> EngineReceipt:
    """One bounded in-container request. No HTTP or external network."""
    if operation not in ("status", "start", "stop") or type(operation) is not str:
        raise LocalEngineUnavailable("Boca engine control operation forbidden")
    before = _check_path(path)
    request = json.dumps({"version": 1, "operation": operation}).encode("ascii") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(50)
            client.connect(str(path))
            if _check_path(path) != before:
                raise LocalEngineUnavailable("Boca engine socket changed during connection")
            client.sendall(request)
            reply = _unique_object(_read_frame(client, _REPLY_LIMIT))
    except (OSError, TimeoutError):
        raise LocalEngineUnavailable("Boca engine socket exchange failed") from None
    if (
        set(reply) != {"version", "state", "changed", "pid"}
        or type(reply["version"]) is not int
        or reply["version"] != 1
        or reply["state"] not in ("RUNNING", "STOPPED", "UNKNOWN")
        or type(reply["state"]) is not str
        or type(reply["changed"]) is not bool
        or type(reply["pid"]) is not int
        or not 1 <= reply["pid"] <= 2**31 - 1
        or reply["state"] == "UNKNOWN"
        or operation == "status"
        and reply["changed"]
    ):
        raise LocalEngineUnavailable("Boca engine operation has no positive receipt")
    state = reply["state"]
    assert state in ("RUNNING", "STOPPED")
    return EngineReceipt(state, bool(reply["changed"]), int(reply["pid"]))


class LocalEngineSocket:
    """A single-threaded, UID-owned control plane in the controller's /tmp."""

    def __init__(self, commands: BetaCommandHost, *, path: Path = DEFAULT_SOCKET) -> None:
        # The CLI-only import in the verified rootless host ZIP needs the
        # stdlib wire receipt, not the controller scheduler/BLACKBOX graph.
        from boca_socios.integration.command_host import BetaCommandHost

        if not isinstance(commands, BetaCommandHost) or not path.is_absolute():
            raise LocalEngineUnavailable("Boca engine controller or path invalid")
        self._commands = commands
        self._path = path
        self._server: socket.socket | None = None
        self._identity: tuple[int, int] | None = None
        self._stopping = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._server is not None or self._thread is not None or self._path.exists():
            raise LocalEngineUnavailable("Boca engine socket already exists")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            old_umask = os.umask(0o077)
            try:
                server.bind(str(self._path))
            finally:
                os.umask(old_umask)
            os.chmod(self._path, 0o600)
            self._identity = _check_path(self._path)
            server.listen(1)
            server.settimeout(0.25)
            self._server = server
            self._thread = Thread(target=self._serve, name="boca-engine-uds", daemon=True)
            self._thread.start()
        except Exception:
            server.close()
            self._remove_owned_socket()
            raise LocalEngineUnavailable("Boca engine control socket unavailable") from None

    def _dispatch(self, operation: ControlOp) -> EngineReceipt:
        """Act only on the actual command thread and return its observed state."""
        if operation == "start":
            changed = self._commands.start_engine()
        elif operation == "stop":
            changed = self._commands.stop_engine()
        elif operation == "status":
            changed = False
        else:
            raise LocalEngineUnavailable("Boca engine operation forbidden")
        state: ControlState = (
            "RUNNING"
            if self._commands.engine_running
            else "STOPPED"
            if self._commands.engine_stopped
            else "UNKNOWN"
        )
        return EngineReceipt(state, changed, os.getpid())

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stopping.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(50)
                try:
                    if not hasattr(socket, "SO_PEERCRED"):
                        raise LocalEngineUnavailable("Boca engine peer identity unavailable")
                    identity = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    pid, uid, gid = struct.unpack("3i", identity)
                    if pid < 1 or uid != os.geteuid() or gid != os.getegid():
                        raise LocalEngineUnavailable("Boca engine peer UID invalid")
                    request = _unique_object(_read_frame(connection, _FRAME_LIMIT))
                    if set(request) != {"version", "operation"} or request["version"] != 1:
                        raise LocalEngineUnavailable("Boca engine frame coordinates invalid")
                    operation = request["operation"]
                    if type(operation) is not str or operation not in ("status", "start", "stop"):
                        raise LocalEngineUnavailable("Boca engine operation forbidden")
                    response = self._dispatch(cast(ControlOp, operation))
                except Exception:
                    response = EngineReceipt("UNKNOWN", False, os.getpid())
                try:
                    connection.sendall(response._as_bytes())
                except (OSError, LocalEngineUnavailable):
                    continue

    def _remove_owned_socket(self) -> None:
        if self._identity is None:
            return
        try:
            if _check_path(self._path) == self._identity:
                self._path.unlink()
        except LocalEngineUnavailable:
            pass

    def close(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=50)
            if self._thread.is_alive():
                raise LocalEngineUnavailable("Boca engine listener stop unverified")
            self._thread = None
        self._remove_owned_socket()
        self._identity = None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("status", "start", "stop"):
        return 2
    try:
        result = request_local_engine(cast(ControlOp, args[0]))
    except LocalEngineUnavailable:
        print("BOCA_ENGINE_CONTROL NO_GO")
        return 1
    print(result._as_bytes().decode("ascii").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
